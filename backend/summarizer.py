import json
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

import yt_dlp

from .downloader import normalize_input_to_url
from .douyin_parser import is_douyin_url, get_douyin_item_info, build_douyin_nowm_url, _default_headers, _opener

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

try:
    from opencc import OpenCC
except Exception:
    OpenCC = None


TEMP_DIR = os.path.join(os.getcwd(), "temp")
SUMMARY_DIR = os.path.join(TEMP_DIR, "summaries")
AUDIO_DIR = os.path.join(TEMP_DIR, "summary_audio")
os.makedirs(SUMMARY_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

SUBTITLE_DIR = os.path.join(TEMP_DIR, "subtitles")
os.makedirs(SUBTITLE_DIR, exist_ok=True)

_TASKS: Dict[str, Dict] = {}
_TASK_LOCK = threading.Lock()
_WHISPER_MODEL_CACHE: Dict[str, WhisperModel] = {}
_WHISPER_MODEL_LOCK = threading.Lock()
_ENV_LOADED = False
_OPENCC_T2S = OpenCC("t2s") if OpenCC is not None else None


def _ts(seconds: float) -> str:
    s = int(max(0, seconds))
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _ts_srt(seconds: float) -> str:
    ms = int(max(0, seconds) * 1000)
    s = ms // 1000
    ms = ms % 1000
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def _ts_vtt(seconds: float) -> str:
    ms = int(max(0, seconds) * 1000)
    s = ms // 1000
    ms = ms % 1000
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"


def _clamp_seconds(x: float, duration: float) -> float:
    v = max(0.0, float(x or 0.0))
    if duration and duration > 0:
        v = min(v, float(duration))
    return v


def _provider_defaults(provider: str) -> tuple[str, str]:
    p = (provider or "").lower().strip()
    if p == "tongyi":
        return "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"
    if p == "deepseek":
        return "https://api.deepseek.com/v1", "deepseek-chat"
    return "https://api.openai.com/v1", "gpt-4o-mini"


def _load_local_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # .env 读取失败时不阻断主流程，仍按系统环境变量继续。
        pass


def _resolve_api_key(provider: str) -> str:
    direct_key = os.getenv("SUMMARY_API_KEY", "").strip()
    if direct_key:
        return direct_key

    p = (provider or "").lower().strip()
    if p == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY", "").strip()
    if p == "tongyi":
        return os.getenv("DASHSCOPE_API_KEY", "").strip()
    return os.getenv("OPENAI_API_KEY", "").strip()


@dataclass
class LlmConfig:
    provider: str
    api_key: str
    base_url: str
    model: str


def _load_llm_config() -> LlmConfig:
    _load_local_env_once()
    provider = os.getenv("SUMMARY_PROVIDER", "openai")
    default_base_url, default_model = _provider_defaults(provider)
    api_key = _resolve_api_key(provider)
    base_url = os.getenv("SUMMARY_BASE_URL", default_base_url).rstrip("/")
    model = os.getenv("SUMMARY_MODEL", default_model).strip()
    if not api_key:
        raise Exception(
            "缺少 API Key：请配置 SUMMARY_API_KEY，或按 provider 配置 "
            "OPENAI_API_KEY / DASHSCOPE_API_KEY / DEEPSEEK_API_KEY（支持项目 .env）"
        )
    return LlmConfig(provider=provider, api_key=api_key, base_url=base_url, model=model)


def _call_chat_completion(cfg: LlmConfig, prompt: str) -> str:
    url = f"{cfg.base_url}/chat/completions"
    payload = {
        "model": cfg.model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "你是一个专业的视频内容分析助手。只输出 JSON，不要输出解释。"},
            {"role": "user", "content": prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise Exception(f"LLM 调用失败: HTTP {e.code} - {detail[:400]}")
    except Exception as e:
        raise Exception(f"LLM 调用失败: {str(e)}")

    try:
        obj = json.loads(raw)
        return obj["choices"][0]["message"]["content"]
    except Exception:
        raise Exception(f"LLM 返回格式异常: {raw[:400]}")


def _call_chat_completion_stream(cfg: LlmConfig, prompt: str) -> Iterator[str]:
    url = f"{cfg.base_url}/chat/completions"
    payload = {
        "model": cfg.model,
        "temperature": 0.2,
        "stream": True,
        "messages": [
            {"role": "system", "content": "你是一个专业的视频内容分析助手。只输出 JSON，不要输出解释。"},
            {"role": "user", "content": prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                chunk = line[len("data:") :].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                    delta = (
                        obj.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content")
                    )
                    if delta:
                        yield str(delta)
                except Exception:
                    continue
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise Exception(f"LLM 流式调用失败: HTTP {e.code} - {detail[:400]}")
    except Exception as e:
        raise Exception(f"LLM 流式调用失败: {str(e)}")


def _extract_json(text: str) -> Dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise Exception("模型输出不是合法 JSON")


def _select_subtitle_url(info: Dict) -> str:
    subtitles = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    lang_priority = ["zh-Hans", "zh-CN", "zh", "en", "en-US"]
    pools = [subtitles, auto]
    for pool in pools:
        for lang in lang_priority:
            entries = pool.get(lang) or []
            for entry in entries:
                u = entry.get("url")
                if u:
                    return u
        for entries in pool.values():
            for entry in entries or []:
                u = entry.get("url")
                if u:
                    return u
    return ""


def _clean_subtitle_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}", " ", text)
    text = re.sub(r"\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}\.\d{3}", " ", text)
    text = re.sub(r"\n\d+\n", "\n", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _to_simplified(text)


def _parse_vtt_or_srt_to_segments(raw: str) -> List[Dict]:
    s = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"^\ufeff", "", s)
    if s.lstrip().upper().startswith("WEBVTT"):
        s = re.sub(r"^WEBVTT[^\n]*\n+", "", s, flags=re.IGNORECASE)
    lines = s.split("\n")

    segs: List[Dict] = []
    i = 0

    def parse_time(t: str) -> float:
        t = (t or "").strip()
        if "," in t:
            t = t.replace(",", ".")
        parts = t.split(":")
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            sec = float(parts[2])
            return h * 3600 + m * 60 + sec
        if len(parts) == 2:
            m = float(parts[0])
            sec = float(parts[1])
            return m * 60 + sec
        return float(t)

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if re.match(r"^\d+$", line):
            i += 1
            line = lines[i].strip() if i < len(lines) else ""
        if "-->" not in line:
            i += 1
            continue
        time_line = line
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        try:
            start_s, end_s = [x.strip() for x in time_line.split("-->", 1)]
            start_s = start_s.split(" ")[0].strip()
            end_s = end_s.split(" ")[0].strip()
            start = parse_time(start_s)
            end = parse_time(end_s)
        except Exception:
            continue
        txt = re.sub(r"<[^>]+>", " ", " ".join(text_lines)).strip()
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            segs.append({"start": start, "end": end, "text": _to_simplified(txt)})
        i += 1
    return segs


def _bilibili_fetch_cc_segments(bvid: str) -> List[Dict]:
    bvid = (bvid or "").strip()
    if not bvid:
        return []
    view_url = "https://api.bilibili.com/x/web-interface/view?bvid=" + urllib.parse.quote(bvid, safe="")
    req = urllib.request.Request(view_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        view_raw = resp.read().decode("utf-8", errors="ignore")
    view_obj = json.loads(view_raw or "{}")
    data = (view_obj.get("data") or {})
    cid = str(data.get("cid") or "").strip()
    if not cid:
        pages = data.get("pages") or []
        if pages and isinstance(pages, list):
            cid = str((pages[0] or {}).get("cid") or "").strip()
    if not cid:
        return []

    player_url = (
        "https://api.bilibili.com/x/player/v2?bvid="
        + urllib.parse.quote(bvid, safe="")
        + "&cid="
        + urllib.parse.quote(cid, safe="")
    )
    req = urllib.request.Request(player_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        player_raw = resp.read().decode("utf-8", errors="ignore")
    player_obj = json.loads(player_raw or "{}")
    subtitle = (((player_obj.get("data") or {}).get("subtitle") or {}))
    sub_list = subtitle.get("subtitles") or []
    if not sub_list:
        return []

    # Prefer human captions (AI=0), then zh, then first
    def score(x: Dict) -> Tuple[int, int]:
        ai = int((x.get("ai_status") or 0))
        lang = str(x.get("lan") or "")
        is_zh = 1 if lang.startswith("zh") else 0
        return (1 if ai == 0 else 0, is_zh)

    chosen = sorted([x for x in sub_list if isinstance(x, dict)], key=score, reverse=True)[0]
    sub_url = str(chosen.get("subtitle_url") or "").strip()
    if not sub_url:
        return []
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url
    req = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        cc_raw = resp.read().decode("utf-8", errors="ignore")
    cc_obj = json.loads(cc_raw or "{}")
    body = cc_obj.get("body") or []
    segs = []
    for it in body:
        if not isinstance(it, dict):
            continue
        start = float(it.get("from") or 0.0)
        end = float(it.get("to") or start)
        text = str(it.get("content") or "").strip()
        if text:
            segs.append({"start": start, "end": end, "text": _to_simplified(text)})
    return segs


def _extract_bvid(url: str) -> str:
    m = re.search(r"/video/(BV[0-9A-Za-z]+)", url or "", flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\b(BV[0-9A-Za-z]{10,})\b", url or "", flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _extract_subtitle_segments(url: str) -> Tuple[List[Dict], str]:
    # Returns (segments, source)
    if "bilibili.com" in (url or ""):
        bvid = _extract_bvid(url)
        if bvid:
            try:
                segs = _bilibili_fetch_cc_segments(bvid)
                if segs:
                    return segs, "bilibili_cc"
            except Exception:
                pass

    ydl_opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    subtitle_url = _select_subtitle_url(info)
    if subtitle_url:
        req = urllib.request.Request(subtitle_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_sub = resp.read().decode("utf-8", errors="ignore")
        segs = _parse_vtt_or_srt_to_segments(raw_sub)
        if segs:
            return segs, "platform_caption"
        cleaned = _clean_subtitle_text(raw_sub)
        if cleaned:
            return [{"start": 0.0, "end": float(info.get("duration") or 0.0), "text": cleaned}], "platform_caption"
    return [], "none"


def _transcribe_segments_by_faster_whisper(audio_path: str) -> List[Dict]:
    if WhisperModel is None:
        raise Exception("faster-whisper 未安装，请执行: pip install faster-whisper")
    model_size = os.getenv("WHISPER_MODEL_SIZE", "tiny")
    device = os.getenv("WHISPER_DEVICE", "cpu").strip().lower() or "cpu"
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

    def _load_model(target_device: str, target_compute_type: str) -> WhisperModel:
        cache_key = f"{model_size}:{target_device}:{target_compute_type}"
        with _WHISPER_MODEL_LOCK:
            model_local = _WHISPER_MODEL_CACHE.get(cache_key)
            if model_local is None:
                model_local = WhisperModel(model_size, device=target_device, compute_type=target_compute_type)
                _WHISPER_MODEL_CACHE[cache_key] = model_local
        return model_local

    try:
        model = _load_model(device, compute_type)
    except Exception as e:
        msg = str(e).lower()
        if ("cublas" in msg or "cuda" in msg or "cudnn" in msg) and device != "cpu":
            model = _load_model("cpu", "int8")
        else:
            raise

    whisper_language = os.getenv("WHISPER_LANGUAGE", "auto").strip().lower()
    transcribe_language = None if whisper_language in ("", "auto", "none") else whisper_language
    segments, _ = model.transcribe(
        audio_path,
        vad_filter=False,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        language=transcribe_language,
    )
    out = []
    for seg in segments:
        t = (seg.text or "").strip()
        if not t:
            continue
        out.append({"start": float(seg.start or 0.0), "end": float(seg.end or seg.start or 0.0), "text": _to_simplified(t)})
    return out


def _segments_to_srt(segments: List[Dict], duration: float = 0.0) -> str:
    lines = []
    idx = 1
    for seg in segments or []:
        start = _clamp_seconds(seg.get("start", 0.0), duration)
        end = _clamp_seconds(seg.get("end", start), duration)
        if end < start:
            end = start
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_ts_srt(start)} --> {_ts_srt(end)}")
        lines.append(text)
        lines.append("")
        idx += 1
    return "\n".join(lines).strip() + "\n"


def _segments_to_vtt(segments: List[Dict], duration: float = 0.0) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments or []:
        start = _clamp_seconds(seg.get("start", 0.0), duration)
        end = _clamp_seconds(seg.get("end", start), duration)
        if end < start:
            end = start
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{_ts_vtt(start)} --> {_ts_vtt(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _segments_to_txt(segments: List[Dict]) -> str:
    lines = []
    for seg in segments or []:
        start = float(seg.get("start") or 0.0)
        text = str(seg.get("text") or "").strip()
        if text:
            lines.append(f"[{_ts(start)}] {text}")
    return "\n".join(lines).strip() + "\n"


def _to_simplified(text: str) -> str:
    if not text:
        return text
    if _OPENCC_T2S is None:
        return text
    try:
        return _OPENCC_T2S.convert(text)
    except Exception:
        return text


def _detect_output_language(text: str) -> str:
    s = str(text or "")
    if not s.strip():
        return "zh"
    zh_count = len(re.findall(r"[\u4e00-\u9fff]", s))
    en_count = len(re.findall(r"[A-Za-z]", s))
    if zh_count >= max(30, en_count // 3):
        return "zh"
    if en_count > 40:
        return "en"
    return "zh"


def _download_audio_for_asr(url: str) -> str:
    out_prefix = os.path.join(AUDIO_DIR, f"audio_{uuid.uuid4().hex}")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_prefix + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        output = ydl.prepare_filename(info)
    if not os.path.exists(output):
        raise Exception("ASR 音频下载失败")
    return output


def _transcribe_by_faster_whisper(audio_path: str) -> str:
    if WhisperModel is None:
        raise Exception("faster-whisper 未安装，请执行: pip install faster-whisper")
    model_size = os.getenv("WHISPER_MODEL_SIZE", "tiny")
    device = os.getenv("WHISPER_DEVICE", "cpu").strip().lower() or "cpu"
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

    def _load_model(target_device: str, target_compute_type: str) -> WhisperModel:
        cache_key = f"{model_size}:{target_device}:{target_compute_type}"
        with _WHISPER_MODEL_LOCK:
            model_local = _WHISPER_MODEL_CACHE.get(cache_key)
            if model_local is None:
                model_local = WhisperModel(
                    model_size,
                    device=target_device,
                    compute_type=target_compute_type,
                )
                _WHISPER_MODEL_CACHE[cache_key] = model_local
        return model_local

    try:
        model = _load_model(device, compute_type)
    except Exception as e:
        msg = str(e).lower()
        # 常见 CUDA 动态库缺失，自动回退 CPU，避免任务直接失败。
        if ("cublas" in msg or "cuda" in msg or "cudnn" in msg) and device != "cpu":
            model = _load_model("cpu", "int8")
        else:
            raise

    whisper_language = os.getenv("WHISPER_LANGUAGE", "auto").strip().lower()
    transcribe_language = None if whisper_language in ("", "auto", "none") else whisper_language
    segments, _ = model.transcribe(
        audio_path,
        vad_filter=False,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        language=transcribe_language,
    )
    texts = []
    for seg in segments:
        t = (seg.text or "").strip()
        if t:
            texts.append(t)
    merged = " ".join(texts).strip()
    if not merged:
        raise Exception("ASR 未识别到有效文本")
    return _to_simplified(merged)


def _extract_douyin_text_without_yt_dlp(url: str) -> tuple[str, Dict]:
    item = get_douyin_item_info(url)
    nowm = build_douyin_nowm_url(item)
    media_path = os.path.join(AUDIO_DIR, f"douyin_{uuid.uuid4().hex}.mp4")
    req = urllib.request.Request(nowm, headers=_default_headers("https://www.douyin.com/"), method="GET")
    with _opener.open(req, timeout=120) as resp, open(media_path, "wb") as fp:
        while True:
            chunk = resp.read(1024 * 128)
            if not chunk:
                break
            fp.write(chunk)
    try:
        text = _transcribe_by_faster_whisper(media_path)
    finally:
        try:
            os.remove(media_path)
        except Exception:
            pass

    video = item.get("video") or {}
    info = {
        "title": item.get("desc") or "N/A",
        "duration": ((video.get("duration", 0) or 0) / 1000),
    }
    return text, info


def _extract_text(url: str) -> tuple[str, Dict, str]:
    if is_douyin_url(url):
        text, info = _extract_douyin_text_without_yt_dlp(url)
        return text, info, "asr"

    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    subtitle_url = _select_subtitle_url(info)
    if subtitle_url:
        req = urllib.request.Request(subtitle_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_sub = resp.read().decode("utf-8", errors="ignore")
        cleaned = _clean_subtitle_text(raw_sub)
        if cleaned:
            return cleaned, info, "platform_caption"

    audio_path = _download_audio_for_asr(url)
    try:
        return _transcribe_by_faster_whisper(audio_path), info, "asr"
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass


def get_task_subtitle_segments(task_id: str) -> Dict:
    task = get_summary_task(task_id)
    result = task.get("result") or {}
    if not result:
        raise Exception("任务未完成，暂无字幕")
    segments = result.get("subtitle_segments") or []
    return {
        "task_id": task_id,
        "source": result.get("subtitle_source") or result.get("transcript_source") or "unknown",
        "segments": segments,
    }


def build_task_subtitle_file(task_id: str, fmt: str) -> str:
    fmt = (fmt or "srt").lower().strip()
    if fmt not in {"srt", "vtt", "txt"}:
        raise Exception("format 仅支持 srt/vtt/txt")
    task = get_summary_task(task_id)
    if task.get("status") != "completed":
        raise Exception("任务未完成，暂不能导出字幕")
    result = task.get("result") or {}
    segments = result.get("subtitle_segments") or []
    duration = float(result.get("duration") or 0.0)
    if not segments:
        # Fallback to transcript as single block
        t = str(result.get("transcript_text") or "").strip()
        if t:
            segments = [{"start": 0.0, "end": duration, "text": t}]
    if fmt == "srt":
        content = _segments_to_srt(segments, duration)
    elif fmt == "vtt":
        content = _segments_to_vtt(segments, duration)
    else:
        content = _segments_to_txt(segments)
    out_path = os.path.join(SUBTITLE_DIR, f"subtitle_{task_id}.{fmt}")
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return out_path


def _build_prompt(title: str, duration: float, content: str) -> str:
    sample = content[:48000]
    return f"""
请基于以下视频转写内容，输出严格 JSON，字段为：
- summary: string[] (3-8条，简洁结论)
- chapters: object[] 每个对象包含 start(number, 秒), end(number, 秒), title(string), points(string[])
- highlights: object[] 每个对象包含 ts(number, 秒), text(string)
- mindmap: object 包含 title(string), children(object[])
  children 节点结构为:
  - name(string)
  - start(number, 秒，可选)
  - end(number, 秒，可选)
  - importance(number, 1-5，可选)
  - children(object[])

约束：
1) 时间戳要覆盖主要内容，且按时间升序
2) chapters 至少 3 段
3) highlights 至少 6 条
4) mindmap 采用 XMind 风格：1 个中心主题 + 4~8 个一级主干；每个主干 2~5 个二级分支
5) 一级主干应覆盖主要章节，名称用名词短语；二级分支优先“方法/结论/注意点”
6) mindmap 最大深度 4，每层最多 8 个节点，节点名称不超过 12 个字
7) 一级主干必须给出 start/end（秒）
8) 输出语言遵循转写主语言（中文内容输出中文，英文内容输出英文）
9) 只输出 JSON，不要输出 markdown 或解释

视频标题: {title}
视频时长(秒): {int(duration or 0)}
转写文本:
{sample}
"""


def _render_markdown(result: Dict) -> str:
    lines = []
    lines.append(f"# {result.get('title') or '视频总结'}")
    lines.append("")
    lines.append(f"- 来源: {result.get('url') or ''}")
    lines.append(f"- 时长: {_ts(result.get('duration') or 0)}")
    lines.append(f"- 输出语言: {result.get('output_language') or 'auto'}")
    lines.append("")
    lines.append("## 摘要")
    for item in result.get("summary") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 章节")
    for ch in result.get("chapters") or []:
        lines.append(f"### {_ts(ch.get('start', 0))} - {_ts(ch.get('end', 0))} | {ch.get('title', '')}")
        for p in ch.get("points") or []:
            lines.append(f"- {p}")
        lines.append("")
    lines.append("## 时间戳要点")
    for h in result.get("highlights") or []:
        lines.append(f"- [{_ts(h.get('ts', 0))}] {h.get('text', '')}")
    lines.append("")
    lines.append("## 字幕/转录")
    lines.append(f"> 来源: {result.get('transcript_source', 'unknown')}")
    lines.append("")
    transcript = (result.get("transcript_text") or "").strip()
    if transcript:
        lines.append(transcript)
        lines.append("")
    return "\n".join(lines)


def _to_int(value, default=0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _normalize_result(parsed: Dict, duration: float) -> Dict:
    total = max(0, _to_int(duration, 0))
    summary = []
    for item in parsed.get("summary") or []:
        text = str(item).strip()
        if text:
            summary.append(text)
    # balanced mode: dedupe and keep concise top lines
    dedup_summary = []
    seen_summary = set()
    for s in summary:
        k = re.sub(r"\s+", "", s).lower()
        if not k or k in seen_summary:
            continue
        seen_summary.add(k)
        dedup_summary.append(s)
    summary = dedup_summary[:10]

    chapters = []
    for ch in parsed.get("chapters") or []:
        start = max(0, _to_int(ch.get("start"), 0))
        end = max(start, _to_int(ch.get("end"), start))
        if total > 0:
            start = min(start, total)
            end = min(end, total)
        title = str(ch.get("title") or "").strip()
        points = [str(p).strip() for p in (ch.get("points") or []) if str(p).strip()]
        chapters.append({
            "start": start,
            "end": end,
            "title": title,
            "points": points[:8],
        })
    chapters.sort(key=lambda x: (x["start"], x["end"]))

    highlights = []
    for h in parsed.get("highlights") or []:
        ts = max(0, _to_int(h.get("ts"), 0))
        if total > 0:
            ts = min(ts, total)
        text = str(h.get("text") or "").strip()
        if text:
            highlights.append({"ts": ts, "text": text})
    highlights.sort(key=lambda x: x["ts"])

    mindmap_raw = parsed.get("mindmap") or {}

    node_seq = {"v": 0}

    def _short_name(name: str, max_len: int = 12) -> str:
        s = (name or "").strip()
        if len(s) <= max_len:
            return s
        return s[:max_len].rstrip() + "…"

    def _name_key(name: str) -> str:
        return re.sub(r"\s+", "", (name or "").lower())

    def _clean_mindmap_node(node: Dict, depth: int = 0) -> Optional[Dict]:
        if depth > 4:
            return None
        name = _short_name(str(node.get("name") or node.get("title") or "").strip(), 12)
        start = max(0, _to_int(node.get("start"), -1))
        end = _to_int(node.get("end"), -1)
        if start < 0:
            start = 0
        if end < 0:
            end = start
        if end < start:
            end = start
        if total > 0:
            start = min(start, total)
            end = min(end, total)
        importance = _to_int(node.get("importance"), 3)
        if importance < 1:
            importance = 1
        if importance > 5:
            importance = 5
        children = []
        for child in node.get("children") or []:
            if isinstance(child, dict):
                cleaned = _clean_mindmap_node(child, depth + 1)
                if cleaned:
                    children.append(cleaned)
        if not name and not children:
            return None
        if not name:
            name = "未命名节点"
        node_seq["v"] += 1
        return {
            "id": f"n{node_seq['v']}",
            "name": name,
            "start": start,
            "end": end,
            "importance": importance,
            "children": children[:8],
        }

    mindmap_title = str(mindmap_raw.get("title") or "视频主题").strip() or "视频主题"
    mindmap_children = []
    for child in mindmap_raw.get("children") or []:
        if isinstance(child, dict):
            cleaned = _clean_mindmap_node(child, 1)
            if cleaned:
                mindmap_children.append(cleaned)

    # sibling 去重，避免同层重复节点影响阅读。
    deduped_children = []
    seen_keys = set()
    for c in mindmap_children:
        k = _name_key(c.get("name", ""))
        if not k or k in seen_keys:
            continue
        seen_keys.add(k)
        deduped_children.append(c)
    mindmap_children = deduped_children

    if not mindmap_children:
        for ch in chapters[:8]:
            node_seq["v"] += 1
            child_nodes = []
            used_point = set()
            for i, p in enumerate((ch.get("points") or [])[:5]):
                ps = _short_name(str(p).strip(), 12)
                pk = _name_key(ps)
                if not ps or pk in used_point:
                    continue
                used_point.add(pk)
                child_nodes.append(
                    {
                        "id": f"n{node_seq['v']}_p{i}",
                        "name": ps,
                        "start": ch.get("start", 0),
                        "end": ch.get("end", ch.get("start", 0)),
                        "importance": 2,
                        "children": [],
                    }
                )
            mindmap_children.append(
                {
                    "id": f"n{node_seq['v']}",
                    "name": _short_name(ch.get("title") or "章节", 12),
                    "start": ch.get("start", 0),
                    "end": ch.get("end", ch.get("start", 0)),
                    "importance": 3,
                    "children": child_nodes,
                }
            )

    # XMind 风格一级主干数量约束：4~8。
    if len(mindmap_children) < 4:
        for ch in chapters:
            if len(mindmap_children) >= 4:
                break
            ck = _name_key(ch.get("title", ""))
            if not ck or any(_name_key(x.get("name", "")) == ck for x in mindmap_children):
                continue
            node_seq["v"] += 1
            mindmap_children.append(
                {
                    "id": f"n{node_seq['v']}",
                    "name": _short_name(ch.get("title") or "章节", 12),
                    "start": ch.get("start", 0),
                    "end": ch.get("end", ch.get("start", 0)),
                    "importance": 3,
                    "children": [],
                }
            )

    # 按重要性+起始时间排序，并限制最大主干数
    mindmap_children.sort(key=lambda x: (-_to_int(x.get("importance"), 3), _to_int(x.get("start"), 0)))
    mindmap_children = mindmap_children[:8]

    mindmap = {"title": _short_name(mindmap_title, 12), "children": mindmap_children}

    if not summary:
        summary = [str(ch.get("title") or "").strip() for ch in chapters[:4] if str(ch.get("title") or "").strip()]

    summary_sections = {
        "overview": summary[:2],
        "outline": [str(ch.get("title") or "").strip() for ch in chapters[:6] if str(ch.get("title") or "").strip()],
        "key_points": summary[2:8] if len(summary) > 2 else summary[:6],
        "one_liner": (summary[0] if summary else ""),
    }

    return {
        "summary": summary,
        "chapters": chapters,
        "highlights": highlights[:30],
        "mindmap": mindmap,
        "summary_sections": summary_sections,
    }


def _build_qa_prompt(question: str, result: Dict) -> str:
    transcript = (result.get("transcript_text") or "")[:20000]
    summary_text = "\n".join(f"- {x}" for x in (result.get("summary") or [])[:8])
    output_language = (result.get("output_language") or "zh").lower()
    answer_lang_hint = "中文" if output_language == "zh" else "English"
    return f"""
你是视频问答助手。请仅根据给定内容回答，若证据不足请明确说“根据现有转录无法确认”。
回答要求：简洁、结构化（最多 5 条），输出语言使用 {answer_lang_hint}。

问题：
{question}

视频标题：
{result.get("title") or "N/A"}

摘要：
{summary_text}

转录（节选）：
{transcript}
""".strip()


def _build_chat_prompt(messages: List[Dict], result: Dict) -> str:
    transcript = (result.get("transcript_text") or "")[:20000]
    summary_text = "\n".join(f"- {x}" for x in (result.get("summary") or [])[:8])
    output_language = (result.get("output_language") or "zh").lower()
    lang = "中文" if output_language == "zh" else "English"
    conv = []
    for m in messages[-20:]:
        role = (m.get("role") or "user").lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        conv.append(f"{role.upper()}: {content}")
    conv_text = "\n".join(conv)
    return f"""
你是视频内容问答助手。请仅根据给定的摘要与转录回答问题，必要时明确说明证据不足。
输出语言：{lang}
回答要求：简洁、结构化（最多 6 条）。

视频标题：
{result.get("title") or "N/A"}

摘要：
{summary_text}

转录（节选）：
{transcript}

对话历史：
{conv_text}

请继续对话，输出 assistant 的回复纯文本：
""".strip()


def chat_with_summary(task_id: str, messages: List[Dict]) -> Dict:
    task = get_summary_task(task_id)
    if task.get("status") != "completed":
        raise Exception("总结任务未完成，暂不能对话")
    result = task.get("result") or {}
    cfg = _load_llm_config()
    prompt = _build_chat_prompt(messages or [], result)
    answer = _call_chat_completion(cfg, prompt).strip()
    if not answer:
        answer = "根据现有转录无法确认。"
    return {"task_id": task_id, "answer": answer, "provider": cfg.provider, "model": cfg.model}


def _run_task(task_id: str, url: str) -> None:
    with _TASK_LOCK:
        _TASKS[task_id]["status"] = "running"
        _TASKS[task_id]["stage"] = "normalizing_url"
    try:
        normalized = normalize_input_to_url(url)
        if not normalized:
            raise Exception("请输入有效的视频URL")
        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "extracting_transcript"
        transcript, info, transcript_source = _extract_text(normalized)
        output_language = _detect_output_language(transcript)
        subtitle_segments: List[Dict] = []
        subtitle_source = "none"
        try:
            subtitle_segments, subtitle_source = _extract_subtitle_segments(normalized)
        except Exception:
            subtitle_segments, subtitle_source = [], "none"
        if not subtitle_segments:
            # If no platform subtitles, generate timestamped segments from ASR
            try:
                audio_path = _download_audio_for_asr(normalized)
                try:
                    subtitle_segments = _transcribe_segments_by_faster_whisper(audio_path)
                    subtitle_source = "asr"
                finally:
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass
            except Exception:
                subtitle_segments = []
        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "calling_llm"
        cfg = _load_llm_config()
        prompt = _build_prompt(info.get("title", "N/A"), info.get("duration", 0), transcript)
        content = _call_chat_completion(cfg, prompt)
        parsed = _extract_json(content)
        normalized_result = _normalize_result(parsed, info.get("duration", 0))
        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "rendering_markdown"
        result = {
            "title": info.get("title", "N/A"),
            "url": normalized,
            "duration": info.get("duration", 0) or 0,
            "summary": normalized_result["summary"],
            "chapters": normalized_result["chapters"],
            "highlights": normalized_result["highlights"],
            "mindmap": normalized_result["mindmap"],
            "summary_sections": normalized_result.get("summary_sections") or {},
            "transcript_source": transcript_source,
            "transcript_text": transcript,
            "subtitle_source": subtitle_source if subtitle_source != "none" else transcript_source,
            "subtitle_segments": subtitle_segments,
            "provider": cfg.provider,
            "model": cfg.model,
            "output_language": output_language,
        }
        markdown = _render_markdown(result)
        md_path = os.path.join(SUMMARY_DIR, f"summary_{task_id}.md")
        with open(md_path, "w", encoding="utf-8") as fp:
            fp.write(markdown)
        result["markdown_file_path"] = md_path

        with _TASK_LOCK:
            _TASKS[task_id]["status"] = "completed"
            _TASKS[task_id]["stage"] = "completed"
            _TASKS[task_id]["result"] = result
            _TASKS[task_id]["updated_at"] = int(time.time())
    except Exception as e:
        with _TASK_LOCK:
            _TASKS[task_id]["status"] = "failed"
            _TASKS[task_id]["stage"] = "failed"
            _TASKS[task_id]["error"] = str(e)
            _TASKS[task_id]["updated_at"] = int(time.time())


def create_summary_task(url: str) -> str:
    return create_summary_task_with_options(url, start_thread=True)


def create_summary_task_with_options(url: str, start_thread: bool = True) -> str:
    task_id = uuid.uuid4().hex
    with _TASK_LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "url": url,
            "status": "pending",
            "stage": "pending",
            "error": None,
            "result": None,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
    if start_thread:
        t = threading.Thread(target=_run_task, args=(task_id, url), daemon=True)
        t.start()
    return task_id


def stream_summary_task(task_id: str) -> Iterator[Dict]:
    task = get_summary_task(task_id)
    url = str(task.get("url") or "").strip()
    if not url:
        raise Exception("任务缺少 url，无法流式执行")

    def emit(event: str, data: Dict) -> Dict:
        return {"event": event, "data": data}

    with _TASK_LOCK:
        if _TASKS[task_id]["status"] not in ("pending",):
            # If already running/completed, just stream current snapshot and exit
            snap = dict(_TASKS[task_id])
            yield emit("stage", {"stage": snap.get("stage"), "status": snap.get("status")})
            if snap.get("status") == "completed":
                yield emit("done", {"result": snap.get("result")})
            if snap.get("status") == "failed":
                yield emit("error", {"error": snap.get("error")})
            return
        _TASKS[task_id]["status"] = "running"
        _TASKS[task_id]["stage"] = "normalizing_url"
        _TASKS[task_id]["updated_at"] = int(time.time())

    yield emit("stage", {"stage": "normalizing_url"})
    try:
        normalized = normalize_input_to_url(url)
        if not normalized:
            raise Exception("请输入有效的视频URL")

        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "extracting_transcript"
            _TASKS[task_id]["updated_at"] = int(time.time())
        yield emit("stage", {"stage": "extracting_transcript"})
        transcript, info, transcript_source = _extract_text(normalized)
        output_language = _detect_output_language(transcript)

        subtitle_segments: List[Dict] = []
        subtitle_source = "none"
        try:
            subtitle_segments, subtitle_source = _extract_subtitle_segments(normalized)
        except Exception:
            subtitle_segments, subtitle_source = [], "none"
        if not subtitle_segments:
            try:
                audio_path = _download_audio_for_asr(normalized)
                try:
                    subtitle_segments = _transcribe_segments_by_faster_whisper(audio_path)
                    subtitle_source = "asr"
                finally:
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass
            except Exception:
                subtitle_segments = []

        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "calling_llm"
            _TASKS[task_id]["updated_at"] = int(time.time())
        yield emit("stage", {"stage": "calling_llm"})

        cfg = _load_llm_config()
        prompt = _build_prompt(info.get("title", "N/A"), info.get("duration", 0), transcript)

        buf = []
        # Try streaming first; if fails, fallback to non-stream
        try:
            for delta in _call_chat_completion_stream(cfg, prompt):
                buf.append(delta)
                yield emit("delta", {"text": delta})
        except Exception:
            content = _call_chat_completion(cfg, prompt)
            buf = [content]
            yield emit("delta", {"text": content})
        content_full = "".join(buf)

        parsed = _extract_json(content_full)
        normalized_result = _normalize_result(parsed, info.get("duration", 0))

        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "rendering_markdown"
            _TASKS[task_id]["updated_at"] = int(time.time())
        yield emit("stage", {"stage": "rendering_markdown"})

        result = {
            "title": info.get("title", "N/A"),
            "url": normalized,
            "duration": info.get("duration", 0) or 0,
            "summary": normalized_result["summary"],
            "chapters": normalized_result["chapters"],
            "highlights": normalized_result["highlights"],
            "mindmap": normalized_result["mindmap"],
            "summary_sections": normalized_result.get("summary_sections") or {},
            "transcript_source": transcript_source,
            "transcript_text": transcript,
            "subtitle_source": subtitle_source if subtitle_source != "none" else transcript_source,
            "subtitle_segments": subtitle_segments,
            "provider": cfg.provider,
            "model": cfg.model,
            "output_language": output_language,
        }
        markdown = _render_markdown(result)
        md_path = os.path.join(SUMMARY_DIR, f"summary_{task_id}.md")
        with open(md_path, "w", encoding="utf-8") as fp:
            fp.write(markdown)
        result["markdown_file_path"] = md_path

        with _TASK_LOCK:
            _TASKS[task_id]["status"] = "completed"
            _TASKS[task_id]["stage"] = "completed"
            _TASKS[task_id]["result"] = result
            _TASKS[task_id]["updated_at"] = int(time.time())

        yield emit("done", {"result": result})
    except Exception as e:
        with _TASK_LOCK:
            _TASKS[task_id]["status"] = "failed"
            _TASKS[task_id]["stage"] = "failed"
            _TASKS[task_id]["error"] = str(e)
            _TASKS[task_id]["updated_at"] = int(time.time())
        yield emit("error", {"error": str(e)})


def get_summary_task(task_id: str) -> Dict:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
    if not task:
        raise Exception("任务不存在")
    return task


def ask_summary_question(task_id: str, question: str) -> Dict:
    q = (question or "").strip()
    if not q:
        raise Exception("问题不能为空")
    task = get_summary_task(task_id)
    if task.get("status") != "completed":
        raise Exception("总结任务未完成，暂不能提问")
    result = task.get("result") or {}
    cfg = _load_llm_config()
    prompt = _build_qa_prompt(q, result)
    answer = _call_chat_completion(cfg, prompt).strip()
    if not answer:
        answer = "根据现有转录无法确认。"
    return {
        "task_id": task_id,
        "question": q,
        "answer": answer,
        "provider": cfg.provider,
        "model": cfg.model,
    }


def _translate_summary_prompt(result: Dict, target_lang: str) -> str:
    target = "中文" if target_lang == "zh" else "English"
    payload = {
        "summary": result.get("summary") or [],
        "chapters": result.get("chapters") or [],
        "highlights": result.get("highlights") or [],
    }
    return f"""
你是翻译助手。把给定 JSON 中所有可读文本翻译为{target}，保持 JSON 结构和字段名不变。
规则：
1) 不要新增字段，不要删除字段
2) 数字和时间戳保持原值
3) 只输出 JSON

输入 JSON:
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def translate_summary(task_id: str, target_lang: str = "zh") -> Dict:
    target = (target_lang or "zh").strip().lower()
    if target not in {"zh", "en"}:
        raise Exception("仅支持 zh 或 en")
    task = get_summary_task(task_id)
    if task.get("status") != "completed":
        raise Exception("总结任务未完成，暂不能翻译")
    result = task.get("result") or {}
    cfg = _load_llm_config()
    prompt = _translate_summary_prompt(result, target)
    content = _call_chat_completion(cfg, prompt)
    parsed = _extract_json(content)
    translated = {
        "summary": parsed.get("summary") or result.get("summary") or [],
        "chapters": parsed.get("chapters") or result.get("chapters") or [],
        "highlights": parsed.get("highlights") or result.get("highlights") or [],
        "target_language": target,
    }
    return translated
