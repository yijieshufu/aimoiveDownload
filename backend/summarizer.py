from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
from contextlib import contextmanager
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import yt_dlp

from .downloader import build_ydl_option_variants, normalize_input_to_url, shorten_windows_path
from .douyin_parser import is_douyin_url, get_douyin_item_info, build_douyin_nowm_url, _default_headers, _opener
from .env_bootstrap import load_dotenv_files
from .summarizer_postprocess import apply_summary_result_enhancements

_FASTER_WHISPER_IMPORT_ERROR: Optional[BaseException] = None
try:
    from faster_whisper import WhisperModel
except Exception as _e:
    WhisperModel = None
    _FASTER_WHISPER_IMPORT_ERROR = _e

try:
    from opencc import OpenCC
except Exception:
    OpenCC = None


TEMP_DIR = os.path.abspath(os.path.join(os.getcwd(), "temp"))
SUMMARY_DIR = os.path.join(TEMP_DIR, "summaries")
os.makedirs(SUMMARY_DIR, exist_ok=True)

SUBTITLE_DIR = os.path.join(TEMP_DIR, "subtitles")
os.makedirs(SUBTITLE_DIR, exist_ok=True)

_TASKS: Dict[str, Dict] = {}
_TASK_LOCK = threading.Lock()
_WHISPER_MODEL_CACHE: Dict[str, Any] = {}
_WHISPER_MODEL_LOCK = threading.Lock()
_OPENCC_T2S = OpenCC("t2s") if OpenCC is not None else None

# B 站 playurl 需 WBI 签名；未签名时接口失败会回退 yt-dlp，在 Windows 上易触发 OSError(22)。
_BILI_WBI_CACHE: Dict[str, Any] = {"ts": 0.0, "key": ""}
_BILI_WBI_TTL_S = 3600.0


def _asr_ytdlp_home_dir() -> str:
    base = os.path.abspath(os.path.join(tempfile.gettempdir(), "aimovie_ytdlp"))
    os.makedirs(base, exist_ok=True)
    # 仅用短路径，不加 \\\\?\\：部分工具/yt-dlp 子进程对扩展路径处理不一致；errno 22 也可能来自超长 argv。
    return shorten_windows_path(base)


def _canonical_asr_page_url(page_url: str) -> str:
    """B 站带 ?t= / 分享后缀时规范成标准 watch 页，减少解析与下游异常。"""
    u = (page_url or "").strip()
    if "bilibili.com" not in u.lower():
        return u
    bvid = _extract_bvid(u)
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}/"
    return u


def _ffmpeg_executable() -> Optional[str]:
    env = (os.environ.get("FFMPEG_BINARY") or "").strip()
    if env and os.path.isfile(env):
        return env
    w = shutil.which("ffmpeg")
    return w if w else None


def _list_files_prefixed(directory: str, prefix: str) -> List[str]:
    """避免 glob 在部分 Win 路径下异常；prefix 为文件名前缀（不含目录）。"""
    out: List[str] = []
    try:
        for name in os.listdir(directory):
            if name.startswith(prefix + "."):
                out.append(os.path.join(directory, name))
    except OSError:
        pass
    return out


@contextmanager
def _asr_windows_temp_env(home: str):
    """让 ffmpeg/子进程与 yt-dlp 使用同一短路径根目录，避免仍写入系统 %TEMP% 触发 Win EINVAL。"""
    if sys.platform != "win32":
        yield
        return
    old_tmp = os.environ.get("TMP")
    old_temp = os.environ.get("TEMP")
    try:
        os.environ["TMP"] = home
        os.environ["TEMP"] = home
        yield
    finally:
        if old_tmp is None:
            os.environ.pop("TMP", None)
        else:
            os.environ["TMP"] = old_tmp
        if old_temp is None:
            os.environ.pop("TEMP", None)
        else:
            os.environ["TEMP"] = old_temp


def _bilibili_get_wbi_key() -> str:
    if time.time() < float(_BILI_WBI_CACHE["ts"]) + _BILI_WBI_TTL_S and _BILI_WBI_CACHE.get("key"):
        return str(_BILI_WBI_CACHE["key"])
    req = urllib.request.Request(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com/",
        },
        method="GET",
    )
    raw = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            break
        except Exception:
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    obj = json.loads(raw or "{}")
    if int(obj.get("code", -1)) != 0:
        return ""
    data = obj.get("data") or {}
    wbi = data.get("wbi_img") or {}

    def _seg(url: str) -> str:
        s = str(url or "")
        return s.rpartition("/")[2].partition(".")[0]

    lookup = _seg(wbi.get("img_url")) + _seg(wbi.get("sub_url"))
    if len(lookup) < 64:
        return ""
    mixin_key_enc_tab = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52,
    ]
    key = "".join(lookup[i] for i in mixin_key_enc_tab)[:32]
    _BILI_WBI_CACHE.update({"key": key, "ts": time.time()})
    return key


def _bilibili_sign_wbi_params(params: Dict[str, Any]) -> Dict[str, Any]:
    wbi_key = _bilibili_get_wbi_key()
    if not wbi_key:
        return params
    p = dict(params)
    p["wts"] = round(time.time())
    flat = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in sorted(p.items())}
    query = urllib.parse.urlencode(flat)
    flat["w_rid"] = hashlib.md5(f"{query}{wbi_key}".encode()).hexdigest()
    return flat


def _raise_if_faster_whisper_unavailable() -> None:
    if WhisperModel is not None:
        return
    err = _FASTER_WHISPER_IMPORT_ERROR
    if isinstance(err, ModuleNotFoundError):
        raise Exception("faster-whisper 未安装，请执行: pip install faster-whisper")
    if err is not None:
        raise Exception(f"faster-whisper 加载失败: {err!r}")
    raise Exception("faster-whisper 未安装，请执行: pip install faster-whisper")


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
    load_dotenv_files()


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


def _parse_json_subtitle_segments(raw: str) -> List[Dict]:
    s = (raw or "").strip()
    if not s:
        return []
    s = re.sub(r"^\ufeff", "", s)
    s = "".join(ch for ch in s if ch >= " " or ch in "\r\n\t")
    decoder = json.JSONDecoder()
    obj = None
    candidates: List[str] = []
    stripped = s.strip()
    if stripped:
        candidates.append(stripped)
        for marker in ("{", "["):
            idx = stripped.find(marker)
            if idx > 0:
                candidates.append(stripped[idx:])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            break
        except Exception:
            try:
                obj, _ = decoder.raw_decode(candidate)
                break
            except Exception:
                continue
    if obj is None:
        obj = {}

    def build_segments(rows: List[Dict[str, Any]]) -> List[Dict]:
        out: List[Dict] = []
        for idx, row in enumerate(rows):
            end = float(row["end"])
            start = float(row["start"])
            if end <= start and idx + 1 < len(rows):
                next_start = float(rows[idx + 1]["start"])
                if next_start > start:
                    end = next_start
            out.append({"start": start, "end": end, "text": row["text"]})
        return out

    def build_row(start: float, duration: float, parts: List[str]) -> Optional[Dict[str, Any]]:
        text = "".join(parts).replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None
        return {
            "start": start,
            "end": start + duration if duration > 0 else start,
            "text": _to_simplified(text),
        }

    if isinstance(obj, dict):
        events = obj.get("events")
        if isinstance(events, list):
            temp_rows: List[Dict[str, Any]] = []
            for event in events:
                if not isinstance(event, dict):
                    continue
                start_ms = event.get("tStartMs")
                try:
                    start = float(start_ms) / 1000.0
                except Exception:
                    continue
                dur_raw = event.get("dDurationMs")
                duration = 0.0
                try:
                    duration = max(0.0, float(dur_raw) / 1000.0)
                except Exception:
                    duration = 0.0
                raw_parts = event.get("segs") or []
                if not isinstance(raw_parts, list):
                    continue
                parts: List[str] = []
                for part in raw_parts:
                    if not isinstance(part, dict):
                        continue
                    text_part = str(part.get("utf8") or "")
                    if text_part:
                        parts.append(text_part)
                row = build_row(start, duration, parts)
                if row:
                    temp_rows.append(row)
            segs = build_segments(temp_rows)
            if segs:
                return segs

        body = obj.get("body")
        if isinstance(body, list):
            segs: List[Dict] = []
            for item in body:
                if not isinstance(item, dict):
                    continue
                try:
                    start = float(item.get("from") or 0.0)
                except Exception:
                    start = 0.0
                try:
                    end = float(item.get("to") or start)
                except Exception:
                    end = start
                text = re.sub(r"\s+", " ", str(item.get("content") or "").replace("\n", " ")).strip()
                if text:
                    segs.append({"start": start, "end": end, "text": _to_simplified(text)})
            if segs:
                return segs

    tstart_matches = list(re.finditer(r'"tStartMs"\s*:\s*(\d+)', s))
    if not tstart_matches:
        return []
    temp_rows = []
    for idx, match in enumerate(tstart_matches):
        start = float(match.group(1)) / 1000.0
        chunk_end = tstart_matches[idx + 1].start() if idx + 1 < len(tstart_matches) else len(s)
        chunk = s[match.start():chunk_end]
        duration = 0.0
        dur_match = re.search(r'"dDurationMs"\s*:\s*(\d+)', chunk)
        if dur_match:
            duration = max(0.0, float(dur_match.group(1)) / 1000.0)
        raw_parts = re.findall(r'"utf8"\s*:\s*"((?:\\.|[^"\\])*)"', chunk)
        parts: List[str] = []
        for raw_part in raw_parts:
            try:
                text_part = json.loads(f'"{raw_part}"')
            except Exception:
                text_part = raw_part
            if text_part:
                parts.append(str(text_part))
        row = build_row(start, duration, parts)
        if row:
            temp_rows.append(row)
    return build_segments(temp_rows)


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


def _segments_to_transcript_text(segments: List[Dict]) -> str:
    lines: List[str] = []
    last_text = ""
    for seg in segments or []:
        text = re.sub(r"\s+", " ", str(seg.get("text") or "")).strip()
        if not text:
            continue
        if text == last_text:
            continue
        lines.append(text)
        last_text = text
    return "\n".join(lines).strip()


def _looks_like_json_caption_blob(text: str) -> bool:
    s = str(text or "").strip()
    if len(s) < 40:
        return False
    if s.startswith("{") and ("wireMagic" in s or '"events"' in s or '"body"' in s):
        return True
    return '"tStartMs"' in s and '"utf8"' in s and '"events"' in s


def _parse_platform_caption_segments(raw_sub: str) -> List[Dict]:
    segs = _parse_vtt_or_srt_to_segments(raw_sub)
    if len(segs) == 1 and _looks_like_json_caption_blob(segs[0].get("text")):
        nested = _parse_json_subtitle_segments(str(segs[0].get("text") or ""))
        if nested:
            return nested
    if segs:
        return segs
    return _parse_json_subtitle_segments(raw_sub)


def _expand_json_caption_blob_segments(segments: List[Dict]) -> List[Dict]:
    if len(segments or []) != 1:
        return segments
    text = str((segments[0] or {}).get("text") or "").strip()
    if not _looks_like_json_caption_blob(text):
        return segments
    nested = _parse_json_subtitle_segments(text)
    return nested or segments


def _normalize_platform_caption_text(text: str) -> str:
    s = str(text or "").strip()
    if not _looks_like_json_caption_blob(s):
        return s
    segs = _parse_json_subtitle_segments(s)
    normalized = _segments_to_transcript_text(segs)
    return normalized or s


def normalize_summary_result_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(result or {})
    segs = normalized.get("subtitle_segments") or []
    segs = _expand_json_caption_blob_segments(segs)
    normalized["subtitle_segments"] = segs

    transcript_source = str(normalized.get("transcript_source") or "").strip()
    transcript_text = str(normalized.get("transcript_text") or "")
    if transcript_source == "platform_caption":
        normalized["transcript_text"] = _normalize_platform_caption_text(transcript_text)
    elif (
        transcript_source == "low_signal_fallback"
        and segs
        and not str(transcript_text or "").lstrip().startswith("【低信号视频兜底模式】")
    ):
        normalized["transcript_text"] = _build_low_signal_fallback_text(
            {
                "title": normalized.get("title"),
                "uploader": normalized.get("uploader"),
                "description": normalized.get("description"),
                "tags": normalized.get("tags"),
            },
            transcript_text,
            segs,
            str(normalized.get("transcript_quality_reason") or ""),
        )
    return normalized


def _extract_bvid(url: str) -> str:
    m = re.search(r"/video/(BV[0-9A-Za-z]+)", url or "", flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\b(BV[0-9A-Za-z]{10,})\b", url or "", flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _bilibili_page_index(url: str) -> int:
    try:
        qs = urllib.parse.urlparse(url or "").query
        p = urllib.parse.parse_qs(qs).get("p", ["1"])[0]
        return max(1, int(p))
    except Exception:
        return 1


def _bilibili_resolve_cid(bvid: str, page: int) -> Optional[str]:
    view_url = "https://api.bilibili.com/x/web-interface/view?bvid=" + urllib.parse.quote(bvid, safe="")
    req = urllib.request.Request(view_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        view_raw = resp.read().decode("utf-8", errors="ignore")
    view_obj = json.loads(view_raw or "{}")
    if int(view_obj.get("code", -1)) != 0:
        return None
    data = view_obj.get("data") or {}
    pages = data.get("pages") or []
    if pages and isinstance(pages, list):
        idx = min(max(page - 1, 0), len(pages) - 1)
        cid = (pages[idx] or {}).get("cid")
        if cid:
            return str(cid)
    cid = data.get("cid")
    return str(cid) if cid else None


def _bilibili_video_referer(bvid: str) -> str:
    return "https://www.bilibili.com/video/" + urllib.parse.quote(bvid, safe="")


def _bilibili_playurl_data(bvid: str, cid: str, *, fnval: int, qn: int) -> Optional[Dict[str, Any]]:
    signed = _bilibili_sign_wbi_params(
        {
            "bvid": bvid,
            "cid": cid,
            "qn": str(qn),
            "fnval": str(fnval),
            "fnver": "0",
            "fourk": "0",
        }
    )
    q = urllib.parse.urlencode(signed)
    play_url = "https://api.bilibili.com/x/player/wbi/playurl?" + q
    req = urllib.request.Request(
        play_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": _bilibili_video_referer(bvid),
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    obj = json.loads(raw or "{}")
    if int(obj.get("code", -1)) != 0:
        return None
    data = obj.get("data")
    return data if isinstance(data, dict) else None


def _bilibili_single_durl_url(data: Dict[str, Any]) -> Optional[str]:
    durl = data.get("durl") or []
    if len(durl) != 1:
        return None
    u = (durl[0] or {}).get("url")
    if not u:
        return None
    s = str(u).strip()
    return s or None


def _bilibili_http_download_to_file(media_url: str, out_path: str, referer: str) -> bool:
    req = urllib.request.Request(
        media_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": referer,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp, open(out_path, "wb") as fp:
            while True:
                chunk = resp.read(1024 * 128)
                if not chunk:
                    break
                fp.write(chunk)
        return bool(os.path.isfile(out_path) and os.path.getsize(out_path) >= 64)
    except Exception:
        try:
            if os.path.isfile(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return False


def _bilibili_multi_durl_concat_mp4(durl: List[Any], tmp_root: str, referer: str) -> Optional[str]:
    """fnval=0 多段 durl（长视频常见）：逐段 urllib 下载后用 ffmpeg concat 合并，避免走 yt-dlp。"""
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg or len(durl) <= 1:
        return None
    part_paths: List[str] = []
    list_path = ""
    out_path = os.path.join(tmp_root, f"aimovie_bili_asr_{uuid.uuid4().hex}.mp4")
    ok = False
    try:
        for i, seg in enumerate(durl):
            if not isinstance(seg, dict):
                return None
            u = seg.get("url")
            if not u:
                return None
            u_s = str(u).strip()
            path_q = urllib.parse.urlparse(u_s).path.lower()
            suf = ".mp4" if ".mp4" in path_q else ".flv" if ".flv" in path_q else ".bin"
            p = os.path.join(tmp_root, f"bili_seg_{i}_{uuid.uuid4().hex}{suf}")
            if not _bilibili_http_download_to_file(u_s, p, referer):
                return None
            part_paths.append(os.path.abspath(p))
        list_path = os.path.join(tmp_root, f"bili_concat_{uuid.uuid4().hex}.txt")
        with open(list_path, "w", encoding="utf-8") as fp:
            for p in part_paths:
                q = p.replace("\\", "/").replace("'", "'\\''")
                fp.write(f"file '{q}'\n")
        kw: Dict[str, Any] = {
            "check": True,
            "timeout": 3600,
            "capture_output": True,
            "text": True,
        }
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_path,
                "-c",
                "copy",
                out_path,
            ],
            **kw,
        )
        ok = bool(os.path.isfile(out_path) and os.path.getsize(out_path) >= 64)
        return out_path if ok else None
    except Exception:
        return None
    finally:
        for p in part_paths:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass
        if list_path:
            try:
                if os.path.isfile(list_path):
                    os.remove(list_path)
            except Exception:
                pass
        if not ok and out_path and os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass


def _bilibili_dash_audio_url_to_m4a_ffmpeg(media_url: str, out_path: str, referer: str) -> bool:
    """
    DASH 音频 URL 常带极长 query（签名）。Windows 下 `ffmpeg -i <超长URL>` 易超命令行上限触发 [Errno 22]。
    先 urllib 落到本地短路径，再 `ffmpeg -i <本地文件>`。
    """
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return False
    tmp_root = os.path.dirname(os.path.abspath(out_path))
    tmp_in = os.path.join(tmp_root, f"bili_dash_{uuid.uuid4().hex}.m4s")
    if not _bilibili_http_download_to_file(media_url, tmp_in, referer):
        return False
    kw: Dict[str, Any] = {
        "check": True,
        "timeout": 900,
        "capture_output": True,
        "text": True,
    }
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                tmp_in,
                "-vn",
                "-c:a",
                "copy",
                out_path,
            ],
            **kw,
        )
        return bool(os.path.isfile(out_path) and os.path.getsize(out_path) >= 64)
    except Exception:
        try:
            if os.path.isfile(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return False
    finally:
        try:
            if os.path.isfile(tmp_in):
                os.remove(tmp_in)
        except Exception:
            pass


def _bilibili_select_dash_audio_url(bvid: str, cid: str) -> Optional[str]:
    signed = _bilibili_sign_wbi_params(
        {
            "bvid": bvid,
            "cid": cid,
            "qn": "80",
            "fnval": "4048",
            "fnver": "0",
            "fourk": "0",
        }
    )
    q = urllib.parse.urlencode(signed)
    play_url = "https://api.bilibili.com/x/player/wbi/playurl?" + q
    req = urllib.request.Request(
        play_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": _bilibili_video_referer(bvid),
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    obj = json.loads(raw or "{}")
    if int(obj.get("code", -1)) != 0:
        return None
    dash = (obj.get("data") or {}).get("dash") or {}
    audios = dash.get("audio") or []
    if not audios:
        return None
    best = max(audios, key=lambda a: int(a.get("bandwidth") or 0))
    u = str(best.get("baseUrl") or best.get("base_url") or "").strip()
    return u or None


def _try_bilibili_dash_audio_download(url: str) -> Optional[str]:
    """
    B 站 ASR：优先 fnval=0 单条渐进 MP4（urllib）；否则 DASH 音频用 ffmpeg 封装为 m4a。
    避免：① DASH .m4s 无 init 的裸拉取 ② 回退 yt-dlp 在 Windows 上的 OSError(22)。
    """
    if "bilibili.com" not in (url or "").lower():
        return None
    bvid = _extract_bvid(url)
    if not bvid:
        return None
    page = _bilibili_page_index(url)
    referer = _bilibili_video_referer(bvid)
    out_path: Optional[str] = None
    try:
        cid = _bilibili_resolve_cid(bvid, page)
        if not cid:
            return None
        tmp_root = _asr_ytdlp_home_dir()

        for qn in (80, 64, 48, 32):
            pdata = _bilibili_playurl_data(bvid, cid, fnval=0, qn=qn)
            if not pdata:
                continue
            durl = pdata.get("durl") or []
            if len(durl) > 1:
                merged = _bilibili_multi_durl_concat_mp4(durl, tmp_root, referer)
                if merged:
                    return merged
            du = _bilibili_single_durl_url(pdata)
            if not du:
                continue
            out_path = os.path.join(tmp_root, f"aimovie_bili_asr_{uuid.uuid4().hex}.mp4")
            if _bilibili_http_download_to_file(du, out_path, referer):
                return out_path
            try:
                if os.path.isfile(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            out_path = None

        audio_url = _bilibili_select_dash_audio_url(bvid, cid)
        if not audio_url:
            return None
        out_path = os.path.join(tmp_root, f"aimovie_bili_asr_{uuid.uuid4().hex}.m4a")
        if _bilibili_dash_audio_url_to_m4a_ffmpeg(audio_url, out_path, referer):
            return out_path
        try:
            if os.path.isfile(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return None
    except Exception:
        try:
            if out_path and os.path.isfile(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return None


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

    base_opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True}
    info = None
    last_error = None
    for ydl_opts in build_ydl_option_variants(base_opts, url):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    break
        except Exception as e:
            last_error = e
    if not info:
        raise Exception(f"解析字幕信息失败: {last_error}")
    subtitle_url = _select_subtitle_url(info)
    if subtitle_url:
        req = urllib.request.Request(subtitle_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_sub = resp.read().decode("utf-8", errors="ignore")
        segs = _parse_platform_caption_segments(raw_sub)
        if segs:
            segs = _expand_json_caption_blob_segments(segs)
            return segs, "platform_caption"
        cleaned = _clean_subtitle_text(raw_sub)
        if cleaned:
            cleaned = _normalize_platform_caption_text(cleaned)
            reparsed = _parse_json_subtitle_segments(cleaned)
            if reparsed:
                return reparsed, "platform_caption"
            return [{"start": 0.0, "end": float(info.get("duration") or 0.0), "text": cleaned}], "platform_caption"
    return [], "none"


def _extract_summary_video_info(url: str) -> Dict[str, Any]:
    base_opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True}
    info = None
    last_error = None
    for ydl_opts in build_ydl_option_variants(base_opts, url):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    break
        except Exception as e:
            last_error = e
    if not info:
        raise Exception(f"瑙ｆ瀽瑙嗛淇℃伅澶辫触: {last_error}")
    return info


def _extract_subtitle_segments_from_info(info: Dict[str, Any]) -> Tuple[List[Dict], str]:
    subtitle_url = _select_subtitle_url(info)
    if subtitle_url:
        req = urllib.request.Request(subtitle_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_sub = resp.read().decode("utf-8", errors="ignore")
        segs = _parse_platform_caption_segments(raw_sub)
        if segs:
            segs = _expand_json_caption_blob_segments(segs)
            return segs, "platform_caption"
        cleaned = _clean_subtitle_text(raw_sub)
        if cleaned:
            cleaned = _normalize_platform_caption_text(cleaned)
            reparsed = _parse_json_subtitle_segments(cleaned)
            if reparsed:
                return reparsed, "platform_caption"
            return [{"start": 0.0, "end": float(info.get("duration") or 0.0), "text": cleaned}], "platform_caption"
    return [], "none"


def _load_whisper_model_cached(model_size: str, device: str, compute_type: str) -> WhisperModel:
    cache_key = f"{model_size}:{device}:{compute_type}"
    with _WHISPER_MODEL_LOCK:
        model_local = _WHISPER_MODEL_CACHE.get(cache_key)
        if model_local is None:
            model_local = WhisperModel(model_size, device=device, compute_type=compute_type)
            _WHISPER_MODEL_CACHE[cache_key] = model_local
    return model_local


def _transcribe_audio_segments(audio_path: str) -> List[Dict]:
    _raise_if_faster_whisper_unavailable()
    model_size = os.getenv("WHISPER_MODEL_SIZE", "tiny")
    device = os.getenv("WHISPER_DEVICE", "cpu").strip().lower() or "cpu"
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

    try:
        model = _load_whisper_model_cached(model_size, device, compute_type)
    except Exception as e:
        msg = str(e).lower()
        if ("cublas" in msg or "cuda" in msg or "cudnn" in msg) and device != "cpu":
            model = _load_whisper_model_cached(model_size, "cpu", "int8")
        else:
            raise

    whisper_language = os.getenv("WHISPER_LANGUAGE", "auto").strip().lower()
    transcribe_language = None if whisper_language in ("", "auto", "none") else whisper_language
    segments, _ = model.transcribe(
        audio_path,
        vad_filter=True,
        beam_size=5,
        best_of=5,
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


def _transcribe_segments_by_faster_whisper(audio_path: str) -> List[Dict]:
    return _transcribe_audio_segments(audio_path)


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


def _is_low_quality_transcript(text: str) -> Tuple[bool, str]:
    t = str(text or "").strip()
    if not t:
        return True, "转写为空"

    info_chars = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", t)
    if len(info_chars) < 80:
        return True, "转写有效字符过少"

    parts = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"[。！？!?；;，,\n]+", t) if str(x).strip()]
    if len(parts) >= 4:
        freq: Dict[str, int] = {}
        for p in parts:
            if len(p) < 6:
                continue
            k = p.lower()
            freq[k] = freq.get(k, 0) + 1
        if freq:
            if max(freq.values()) >= 4:
                return True, "转写子句重复率过高"

    compact = re.sub(r"\s+", "", t.lower())
    if len(compact) >= 64:
        n = 8
        grams: Dict[str, int] = {}
        for i in range(0, len(compact) - n + 1):
            g = compact[i : i + n]
            grams[g] = grams.get(g, 0) + 1
        if grams and max(grams.values()) >= 6:
            return True, "转写存在明显循环重复片段"

    lower_t = t.lower()
    suspicious_phrases = [
        "the problem is solved because the problem is solved",
        "music",
        "问题被解决因为问题被解决",
        "无意义的重复",
    ]
    hit = sum(1 for p in suspicious_phrases if p in lower_t)
    if hit >= 2:
        return True, "转写命中低信号噪声短语"

    # 4) 词汇多样性过低：常见于“音乐背景 + 模糊口播”导致的重复短句
    words = [w for w in re.split(r"\s+", re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", t)) if w]
    if len(words) >= 40:
        uniq = len(set(w.lower() for w in words))
        diversity = uniq / max(1, len(words))
        if diversity < 0.22:
            return True, "转写词汇多样性过低"

    return False, ""


def _clean_noisy_asr_text(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return ""

    # 去掉常见噪声短语与无信息片段
    noise_patterns = [
        r"\bmusic\b",
        r"the problem is solved because the problem is solved",
        r"problem is solved",
        r"无意义(?:的)?重复",
        r"背景音乐",
    ]
    lowered = t.lower()
    for p in noise_patterns:
        lowered = re.sub(p, " ", lowered, flags=re.IGNORECASE)
    # 用原始文本再做一次同位替换，避免全小写
    cleaned = t
    for p in noise_patterns:
        cleaned = re.sub(p, " ", cleaned, flags=re.IGNORECASE)

    # 句子级去重：保留首次出现，过滤明显重复口水句
    raw_parts = re.split(r"[。！？!?；;\n]+", cleaned)
    seen = set()
    kept: List[str] = []
    for part in raw_parts:
        s = re.sub(r"\s+", " ", str(part or "")).strip()
        if len(s) < 8:
            continue
        key = re.sub(r"\s+", "", s).lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(s)
        if len(kept) >= 80:
            break

    out = "。".join(kept).strip()
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _build_douyin_context_text(item: Dict) -> str:
    desc = str(item.get("desc") or "").strip()
    author = str((item.get("author") or {}).get("nickname") or "").strip()
    text_extra = item.get("text_extra") or []
    tags: List[str] = []
    if isinstance(text_extra, list):
        for it in text_extra:
            if not isinstance(it, dict):
                continue
            tag = str(it.get("hashtag_name") or "").strip()
            if tag:
                tags.append(tag)
    tags = [t for i, t in enumerate(tags) if t and t not in tags[:i]]

    lines: List[str] = []
    if desc:
        lines.append(f"视频文案：{desc}")
    if author and author != "N/A":
        lines.append(f"作者：{author}")
    if tags:
        lines.append("话题标签：" + "、".join(tags[:12]))
    return "\n".join(lines).strip()


def _build_generic_context_text(info: Dict[str, Any]) -> str:
    title = str(info.get("title") or "").strip()
    uploader = str(info.get("uploader") or info.get("channel") or info.get("author") or "").strip()
    description = re.sub(r"\s+", " ", str(info.get("description") or "")).strip()
    tags_raw = info.get("tags") or info.get("categories") or []

    tags: List[str] = []
    if isinstance(tags_raw, list):
        for item in tags_raw:
            text = str(item or "").strip()
            if text and text not in tags:
                tags.append(text)
    elif isinstance(tags_raw, str) and tags_raw.strip():
        tags.append(tags_raw.strip())

    lines: List[str] = []
    if title:
        lines.append(f"视频标题：{title}")
    if uploader and uploader != "N/A":
        lines.append(f"作者：{uploader}")
    if description:
        if len(description) > 360:
            description = description[:360].rstrip() + "…"
        lines.append(f"视频简介：{description}")
    if tags:
        lines.append("话题标签：" + "、".join(tags[:12]))
    return "\n".join(lines).strip()


def _build_low_signal_fallback_text(
    info: Dict[str, Any],
    transcript: str,
    subtitle_segments: List[Dict],
    reason: str,
) -> str:
    lines: List[str] = ["【低信号视频兜底模式】以下内容基于标题、简介、可用字幕片段整理，细节需二次核实。"]

    meta = _build_generic_context_text(info)
    if meta:
        lines.append(meta)

    seg_lines: List[str] = []
    seen_seg = set()
    for seg in subtitle_segments or []:
        text = re.sub(r"\s+", " ", str(seg.get("text") or "")).strip()
        key = re.sub(r"\s+", "", text).lower()
        if len(text) < 8 or not key or key in seen_seg:
            continue
        seen_seg.add(key)
        seg_lines.append(f"- [{_ts(float(seg.get('start') or 0.0))}] {text}")
        if len(seg_lines) >= 10:
            break
    if seg_lines:
        lines.append("可用字幕片段：")
        lines.extend(seg_lines)

    cleaned = _clean_noisy_asr_text(transcript)
    if cleaned:
        sentence_lines: List[str] = []
        seen_sentence = set()
        for part in re.split(r"[。！？!?；;\n]+", cleaned):
            text = re.sub(r"\s+", " ", str(part or "")).strip()
            key = re.sub(r"\s+", "", text).lower()
            if len(text) < 12 or not key or key in seen_sentence:
                continue
            seen_sentence.add(key)
            sentence_lines.append(f"- {text}")
            if len(sentence_lines) >= 6:
                break
        if sentence_lines:
            lines.append("转写摘录：")
            lines.extend(sentence_lines)

    lines.append(f"低信号原因：{reason}")
    return "\n".join(line for line in lines if line).strip()


def _iter_audio_format_dicts(info: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    fmts = info.get("formats") or []
    if isinstance(fmts, list) and fmts:
        for f in fmts:
            if isinstance(f, dict):
                yield f
        return
    if isinstance(info, dict) and info.get("url") and info.get("acodec"):
        yield info


def _pick_best_direct_http_audio(info: Dict[str, Any]) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """
    选取「单条 HTTP(S) URL、无分片」的纯音频流，供 urllib 直拉，绕开 FragmentFD/ffmpeg 在 Windows 上的 EINVAL。
    """
    best_abr = -1.0
    best: Optional[Tuple[str, str, Dict[str, Any]]] = None
    for f in _iter_audio_format_dicts(info):
        acodec = f.get("acodec")
        vcodec = f.get("vcodec")
        if not acodec or acodec == "none":
            continue
        if vcodec and vcodec != "none":
            continue
        if f.get("fragments"):
            continue
        media_url = f.get("url")
        if not media_url or not isinstance(media_url, str):
            continue
        proto = str(f.get("protocol") or "").lower()
        if "m3u8" in proto:
            continue
        low_u = media_url.lower().split("?", 1)[0]
        if low_u.endswith(".m3u8") or low_u.endswith(".mpd"):
            continue
        abr = float(f.get("abr") or f.get("tbr") or 0)
        ext = str(f.get("ext") or "m4a").strip() or "m4a"
        if abr >= best_abr:
            best_abr = abr
            best = (media_url, ext, f)
    return best


def _try_asr_direct_http_download(page_url: str, home: str) -> Optional[str]:
    probe_base: Dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlistend": 1,
    }
    info: Optional[Dict[str, Any]] = None
    for ydl_opts in build_ydl_option_variants(probe_base, page_url):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(page_url, download=False)
            if info:
                break
        except Exception:
            continue
    if not info:
        return None
    picked = _pick_best_direct_http_audio(info)
    if not picked:
        return None
    media_url, ext, fmt = picked
    out_path = os.path.join(home, f"asr_http_{uuid.uuid4().hex}.{ext}")
    hdrs: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    if "bilibili.com" in (page_url or "").lower():
        hdrs.setdefault("Referer", "https://www.bilibili.com/")
    elif "youtube.com" in (page_url or "").lower() or "youtu.be" in (page_url or "").lower():
        hdrs.setdefault("Referer", "https://www.youtube.com/")
    fmt_h = fmt.get("http_headers")
    if isinstance(fmt_h, dict):
        hdrs = {**hdrs, **{str(k): str(v) for k, v in fmt_h.items() if v is not None}}
    req = urllib.request.Request(media_url, headers=hdrs, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp, open(out_path, "wb") as fp:
            while True:
                chunk = resp.read(1024 * 128)
                if not chunk:
                    break
                fp.write(chunk)
        if not os.path.isfile(out_path) or os.path.getsize(out_path) < 64:
            try:
                os.remove(out_path)
            except Exception:
                pass
            return None
        return out_path
    except Exception:
        try:
            if os.path.isfile(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return None


def _download_audio_for_asr(url: str) -> str:
    page_url = _canonical_asr_page_url((normalize_input_to_url(url) or (url or "").strip()).strip())
    if not page_url:
        raise Exception("ASR 音频下载失败：无效的视频链接")

    bili_path = _try_bilibili_dash_audio_download(page_url)
    if bili_path:
        return bili_path
    # 绝对 outtmpl + 短路径/长路径 home，减轻 Win 下 EINVAL；临时目录显式 _tmp。
    home = _asr_ytdlp_home_dir()
    tmp_sub = os.path.join(home, "_tmp")
    os.makedirs(tmp_sub, exist_ok=True)

    direct_path = _try_asr_direct_http_download(page_url, home)
    if direct_path:
        return direct_path

    stem = f"asr_{uuid.uuid4().hex}"
    out_tmpl_abs = os.path.normpath(os.path.join(home, stem + ".%(ext)s"))
    base_opts: Dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": {"default": out_tmpl_abs},
        "paths": {"home": home, "temp": "_tmp"},
        "concurrent_fragment_downloads": 1,
        "hls_prefer_native": True,
        "no_keep_fragments": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nopart": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "writethumbnail": False,
        "writeinfojson": False,
        "writedescription": False,
    }
    last_error = None
    for ydl_opts in build_ydl_option_variants(base_opts, page_url):
        try:
            with _asr_windows_temp_env(home):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(page_url, download=True)
            break
        except Exception as e:
            last_error = e
    else:
        raise Exception(f"ASR 音频下载失败: {last_error}")
    files = _list_files_prefixed(home, stem)
    if not files:
        raise Exception("ASR 音频下载失败：未找到输出文件")
    return max(files, key=os.path.getsize)


def _transcribe_by_faster_whisper(audio_path: str) -> str:
    segments = _transcribe_audio_segments(audio_path)
    merged = " ".join(str(seg.get("text") or "").strip() for seg in segments if str(seg.get("text") or "").strip()).strip()
    if not merged:
        raise Exception("ASR 鏈瘑鍒埌鏈夋晥鏂囨湰")
    return merged

    _raise_if_faster_whisper_unavailable()
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
        vad_filter=True,
        beam_size=5,
        best_of=5,
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
    context_text = _build_douyin_context_text(item)
    nowm = build_douyin_nowm_url(item)
    tmp_root = os.path.abspath(tempfile.gettempdir())
    media_path = os.path.join(tmp_root, f"aimovie_douyin_{uuid.uuid4().hex}.mp4")
    text = ""
    asr_error = ""
    try:
        req = urllib.request.Request(nowm, headers=_default_headers("https://www.douyin.com/"), method="GET")
        with _opener.open(req, timeout=120) as resp, open(media_path, "wb") as fp:
            while True:
                chunk = resp.read(1024 * 128)
                if not chunk:
                    break
                fp.write(chunk)
        text = _transcribe_by_faster_whisper(media_path)
    except Exception as e:
        asr_error = str(e)
    finally:
        try:
            os.remove(media_path)
        except Exception:
            pass

    video = item.get("video") or {}
    info = {
        "title": item.get("desc") or "N/A",
        "duration": ((video.get("duration", 0) or 0) / 1000),
        "douyin_context_text": context_text,
    }
    if asr_error:
        info["asr_error"] = asr_error
    if not text:
        if context_text:
            info["douyin_force_context"] = True
            return context_text, info
        raise Exception(asr_error or "抖音音频下载或转写失败")

    cleaned_asr = _clean_noisy_asr_text(text)
    low_after_clean, _ = _is_low_quality_transcript(cleaned_asr)
    # 抖音知识类短视频常见“语音信息弱、画面文案强”：清洗后仍低质量则直接弃用 ASR，避免污染总结
    if context_text and low_after_clean:
        text = context_text
        info["douyin_force_context"] = True
    elif context_text:
        text = (context_text + "\n\n转写文本：\n" + cleaned_asr).strip()
    else:
        text = cleaned_asr or text
    return text, info


def _extract_text(
    url: str,
    stage_callback: Optional[Callable[[str], None]] = None,
) -> tuple[str, Dict, str, List[Dict], str]:
    if is_douyin_url(url):
        if callable(stage_callback):
            stage_callback("downloading_audio")
        text, info = _extract_douyin_text_without_yt_dlp(url)
        if bool(info.get("douyin_force_context")):
            return text, info, "douyin_context_fallback", [], "none"
        low_q, _ = _is_low_quality_transcript(text)
        if low_q:
            fallback = str(info.get("douyin_context_text") or "").strip()
            if fallback:
                return fallback, info, "douyin_context", [], "none"
        return text, info, "asr", [], "none"

    if callable(stage_callback):
        stage_callback("fetching_subtitles")
    info = _extract_summary_video_info(url)

    subtitle_segments: List[Dict] = []
    subtitle_source = "none"
    if "bilibili.com" in (url or ""):
        bvid = _extract_bvid(url)
        if bvid:
            try:
                subtitle_segments = _bilibili_fetch_cc_segments(bvid)
                if subtitle_segments:
                    subtitle_source = "bilibili_cc"
            except Exception:
                subtitle_segments = []
                subtitle_source = "none"
    if not subtitle_segments:
        subtitle_segments, subtitle_source = _extract_subtitle_segments_from_info(info)
    subtitle_segments = _expand_json_caption_blob_segments(subtitle_segments)
    if subtitle_segments:
        text = _normalize_platform_caption_text(_segments_to_transcript_text(subtitle_segments))
        if text:
            return text, info, "platform_caption", subtitle_segments, (subtitle_source if subtitle_source != "none" else "platform_caption")

    if callable(stage_callback):
        stage_callback("downloading_audio")
    audio_path = _download_audio_for_asr(normalize_input_to_url(url) or url)
    try:
        if callable(stage_callback):
            stage_callback("transcribing_audio")
        asr_segments = _transcribe_audio_segments(audio_path)
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass

    transcript = _segments_to_transcript_text(asr_segments)
    if not transcript:
        raise Exception("ASR 鏈瘑鍒埌鏈夋晥鏂囨湰")
    return transcript, info, "asr", asr_segments, "asr"

    if is_douyin_url(url):
        text, info = _extract_douyin_text_without_yt_dlp(url)
        if bool(info.get("douyin_force_context")):
            return text, info, "douyin_context_fallback"
        low_q, _ = _is_low_quality_transcript(text)
        if low_q:
            fallback = str(info.get("douyin_context_text") or "").strip()
            if fallback:
                # 抖音场景在 ASR 低质时，至少基于文案做结构化总结，避免循环废话
                return fallback, info, "douyin_context"
        return text, info, "asr"

    base_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    info = None
    last_error = None
    for ydl_opts in build_ydl_option_variants(base_opts, url):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    break
        except Exception as e:
            last_error = e
    if not info:
        raise Exception(f"解析视频信息失败: {last_error}")

    subtitle_url = _select_subtitle_url(info)
    if subtitle_url:
        req = urllib.request.Request(subtitle_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_sub = resp.read().decode("utf-8", errors="ignore")
        segs = _parse_platform_caption_segments(raw_sub)
        if segs:
            segs = _expand_json_caption_blob_segments(segs)
            text = _segments_to_transcript_text(segs)
            if text:
                text = _normalize_platform_caption_text(text)
                return text, info, "platform_caption"
        cleaned = _clean_subtitle_text(raw_sub)
        if cleaned:
            cleaned = _normalize_platform_caption_text(cleaned)
            return cleaned, info, "platform_caption"

    audio_path = _download_audio_for_asr(normalize_input_to_url(url) or url)
    try:
        return _transcribe_by_faster_whisper(audio_path), info, "asr"
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass


def get_task_subtitle_segments(task_id: str) -> Dict:
    task = get_summary_task(task_id)
    result = normalize_summary_result_payload(task.get("result") or {})
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
    result = normalize_summary_result_payload(task.get("result") or {})
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


def _build_prompt(title: str, duration: float, content: str, low_signal_mode: bool = False) -> str:
    sample = content[:48000]
    extra_rule = ""
    if low_signal_mode:
        extra_rule = (
            "12) 当前输入以标题/标签等元数据为主，若细节不足，请输出“可执行学习提纲（待核实）”，"
            "禁止仅输出“无法提取/无信息”等消极描述。"
        )
    return f"""
请基于以下视频转写内容，输出严格 JSON，用于生成「AI笔记」。字段为：
- summary: string[] (3-10条，每条 20~80 字为宜；优先可执行结论/方法/注意事项，避免空泛套话)
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
5) 一级主干必须与 chapters 对齐：每个一级节点的 name 必须与某一 chapter 的 title 完全一致（从 chapters 复制原文，勿改写）；其 start/end 与该 chapter 一致；二级分支优先概括该章 points 中的要点（短语）
6) mindmap 最大深度 4，每层最多 8 个节点，节点名称不超过 12 个字
7) 一级主干必须给出 start/end（秒）
8) 禁止编造转写中未出现的事实；不确定内容不要写进 summary/highlights
9) summary 要尽量符合“短笔记卡片”风格：一句一义，尽量可复制、可执行
10) 输出语言遵循转写主语言（中文内容输出中文，英文内容输出英文）
11) 只输出 JSON，不要输出 markdown 或解释
{extra_rule}

视频标题: {title}
视频时长(秒): {int(duration or 0)}
转写文本:
{sample}
"""


def _build_prompt_stream_markdown(
    title: str,
    duration: float,
    content: str,
    low_signal_mode: bool = False,
) -> str:
    """流式总结专用：模型输出可读 Markdown，前端实时渲染；服务端再解析为结构化结果。"""
    sample = content[:48000]
    total = int(duration or 0)
    low_signal_hint = ""
    if low_signal_mode:
        low_signal_hint = (
            "\n额外要求（低信号兜底模式）：若转写细节不足，请基于标题/标签给出“学习提纲（待核实）”，"
            "仍需产出完整结构化章节与要点，不要反复输出“无有效信息”。"
        )
    return f"""
请基于以下视频转写内容，只输出 Markdown（不要 JSON、不要用 ``` 围栏、不要前言或结语）。
目标是产出「抖音风格可读 AI笔记」：短句、清晰层级、可执行。

必须使用下列二级标题，且「## 」单独起行、标题文字与下方一致：

## 视频概述

## 内容大纲

## 章节与时间轴

## 时间戳要点

## 核心知识要点

## 思维导图骨架

各节格式（务必遵守，便于解析）：
1) 视频概述：3~8 条，每行一条，以 `- ` 开头，20~80 字为宜，尽量“短笔记卡片”风格。
2) 内容大纲：至少 4 条，编号列表 `1. **短标题**：说明`（短标题可用 ** 加粗）。
3) 章节与时间轴：至少 3 章。每章第一行必须是三级标题，格式为 `### m:ss - m:ss | 章节标题`（若超过一小时可用 `h:mm:ss`）。总时长约 {total} 秒，时间不要越界。三级标题下一行起用 `- ` 写 2~4 条要点。
4) 时间戳要点：至少 6 条，每行 `- [m:ss] 要点` 或 `- [h:mm:ss] 要点`，时间升序。
5) 核心知识要点：6~12 条，每行以 `- ` 或 `* ` 开头，优先“方法/原则/注意事项/适用场景”。
6) 思维导图骨架：一级行以 `- ` 开头（主题与大纲对应），每个主题下的子点用两个空格缩进后再 `- ` 开头（每主题 2~4 个子点）。

禁止编造转写中未出现的事实。输出语言与转写主语言一致。
{low_signal_hint}

视频标题: {title}
视频时长(秒): {total}
转写文本:
{sample}
"""


def _parse_clock_to_seconds(hms: str) -> int:
    hms = (hms or "").strip()
    if not hms:
        return 0
    parts = hms.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return 0


def _split_markdown_h2_sections(md: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    current: Optional[str] = None
    buf: List[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^##\s+", stripped) and not re.match(r"^###\s+", stripped):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = re.sub(r"^##\s+", "", stripped).strip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _pick_section_body(sections: Dict[str, str], *needles: str) -> str:
    for title, body in sections.items():
        t = re.sub(r"\s+", "", title or "")
        for n in needles:
            if n in t or t in n:
                return body
    return ""


def _bullet_lines(text: str) -> List[str]:
    out: List[str] = []
    for line in (text or "").split("\n"):
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s.startswith("* "):
            out.append(s[2:].strip())
    return [x for x in out if x]


def _markdown_stream_to_parsed(md: str, video_title: str, duration: float) -> Dict:
    sections = _split_markdown_h2_sections(md or "")
    overview = _pick_section_body(sections, "视频概述", "概述")
    outline_sec = _pick_section_body(sections, "内容大纲", "大纲")
    chapters_sec = _pick_section_body(sections, "章节与时间轴", "章节")
    hl_sec = _pick_section_body(sections, "时间戳要点", "要点时间轴")
    keys_sec = _pick_section_body(sections, "核心知识要点", "知识要点")
    total = max(0, _to_int(duration, 0))

    summary: List[str] = []
    summary.extend(_bullet_lines(overview))
    summary.extend(_bullet_lines(keys_sec))

    chapters: List[Dict] = []
    chap_header = re.compile(
        r"^###\s+(\d+:\d+(?::\d+)?)\s*-\s*(\d+:\d+(?::\d+)?)\s*\|\s*(.+)$"
    )
    current_ch: Optional[Dict] = None
    for line in (chapters_sec or "").split("\n"):
        raw = line.rstrip()
        m = chap_header.match(raw.strip())
        if m:
            if current_ch:
                chapters.append(current_ch)
            s0 = _parse_clock_to_seconds(m.group(1))
            s1 = _parse_clock_to_seconds(m.group(2))
            if total > 0:
                s0 = min(max(0, s0), total)
                s1 = min(max(s0, s1), total)
            else:
                s1 = max(s0, s1)
            current_ch = {
                "start": s0,
                "end": s1,
                "title": m.group(3).strip(),
                "points": [],
            }
        elif current_ch and raw.strip().startswith("- "):
            pt = raw.strip()[2:].strip()
            if pt:
                current_ch["points"].append(pt)
    if current_ch:
        chapters.append(current_ch)

    highlights: List[Dict] = []
    hl_line = re.compile(r"^-\s*\[(\d+:\d+(?::\d+)?)\]\s*(.+)$")
    for line in (hl_sec or "").split("\n"):
        s = line.strip()
        m = hl_line.match(s)
        if m:
            ts = _parse_clock_to_seconds(m.group(1))
            if total > 0:
                ts = min(max(0, ts), total)
            tx = m.group(2).strip()
            if tx:
                highlights.append({"ts": ts, "text": tx})

    mindmap_children: List[Dict] = []
    mm_body = _pick_section_body(sections, "思维导图骨架", "思维导图")
    last_l1: Optional[Dict] = None
    for line in (mm_body or "").split("\n"):
        if not line.strip():
            continue
        if re.match(r"^-\s+", line):
            name = re.sub(r"^-\s+", "", line.strip()).strip()
            name = re.sub(r"\*\*([^*]+)\*\*", r"\1", name)
            if name:
                last_l1 = {"name": name[:80], "start": 0, "end": 0, "importance": 3, "children": []}
                mindmap_children.append(last_l1)
        elif re.match(r"^\s{2,}-\s+", line) and last_l1 is not None:
            sub = re.sub(r"^\s+-\s+", "", line.strip()).strip()
            sub = re.sub(r"\*\*([^*]+)\*\*", r"\1", sub)
            if sub:
                last_l1.setdefault("children", []).append(
                    {"name": sub[:80], "start": 0, "end": 0, "importance": 2, "children": []}
                )

    if not chapters:
        for line in (outline_sec or "").split("\n"):
            m = re.match(r"^\d+\.\s+(.+)$", line.strip())
            if not m:
                continue
            title = re.sub(r"\*\*([^*]+)\*\*", r"\1", m.group(1).strip())
            title = title.split("：", 1)[0].strip() if title else ""
            if title:
                est = min(len(chapters) * 60, max(0, total - 60))
                chapters.append(
                    {
                        "start": est,
                        "end": min(est + 60, total) if total else est + 60,
                        "title": title,
                        "points": [],
                    }
                )

    mm: Dict = {"title": (video_title or "视频主题")[:80], "children": mindmap_children[:12]}

    return {
        "summary": summary,
        "chapters": chapters,
        "highlights": highlights,
        "mindmap": mm,
    }


def _coerce_stream_completion_to_parsed(content_full: str, video_title: str, duration: float) -> Dict:
    """流式结束：优先解析 Markdown；若失败则回退 JSON。"""
    text = (content_full or "").strip()
    if not text:
        raise Exception("模型输出为空")
    md_parsed = _markdown_stream_to_parsed(text, video_title, duration)
    if md_parsed.get("summary") or md_parsed.get("chapters") or md_parsed.get("highlights"):
        return md_parsed
    try:
        return _extract_json(text)
    except Exception:
        return md_parsed


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

    note_sections = {
        "overview": list(summary_sections.get("overview") or []),
        "outline": list(summary_sections.get("outline") or []),
        "key_takeaways": list(summary_sections.get("key_points") or []),
        "one_liner": str(summary_sections.get("one_liner") or ""),
    }
    timeline_notes = [{"ts": int(h.get("ts") or 0), "text": str(h.get("text") or "")} for h in highlights[:30]]

    return {
        "summary": summary,
        "chapters": chapters,
        "highlights": highlights[:30],
        "mindmap": mindmap,
        "summary_sections": summary_sections,
        "note_sections": note_sections,
        "key_takeaways": list(note_sections.get("key_takeaways") or []),
        "timeline_notes": timeline_notes,
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


def _strip_chat_code_fence(s: str) -> str:
    t = (s or "").strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)```$", t, re.I)
    if m:
        return m.group(1).strip()
    return t


def _normalize_chat_answer_text(raw: str) -> str:
    """将模型偶发的 JSON（如 {\"回答\": [...]}）转为可读纯文本；失败则返回去围栏后的原文。"""
    text = _strip_chat_code_fence((raw or "").strip())
    if not text:
        return ""
    try:
        obj = json.loads(text)
        if isinstance(obj, str):
            return obj.strip()
        if isinstance(obj, list):
            lines = [f"{i + 1}. {str(x).strip()}" for i, x in enumerate(obj) if str(x).strip()]
            return "\n".join(lines) if lines else ""
        if isinstance(obj, dict):
            for k in ("回答", "answer", "reply", "content", "response", "text"):
                if k not in obj:
                    continue
                v = obj[k]
                if isinstance(v, list):
                    lines = [f"{i + 1}. {str(x).strip()}" for i, x in enumerate(v) if str(x).strip()]
                    if lines:
                        return "\n".join(lines)
                    continue
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except Exception:
        pass
    return text


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
严禁输出 JSON、代码块或 Markdown 围栏；不要用 {{"回答": [...]}} 等形式。请直接输出纯文本：可用空行分段，或 1. 2. 3. 编号列表。

视频标题：
{result.get("title") or "N/A"}

摘要：
{summary_text}

转录（节选）：
{transcript}

对话历史：
{conv_text}

请继续对话，直接输出 assistant 的回复（仅纯文本）：
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
    else:
        normalized = _normalize_chat_answer_text(answer)
        if normalized:
            answer = normalized
    return {"task_id": task_id, "answer": answer, "provider": cfg.provider, "model": cfg.model}


def _run_task(task_id: str, url: str) -> None:
    with _TASK_LOCK:
        _TASKS[task_id]["status"] = "running"
        _TASKS[task_id]["stage"] = "normalizing_url"
    try:
        normalized = normalize_input_to_url(url)
        if not normalized:
            raise Exception("请输入有效的视频URL")
        def update_stage(stage: str) -> None:
            with _TASK_LOCK:
                _TASKS[task_id]["stage"] = stage
                _TASKS[task_id]["updated_at"] = int(time.time())

        update_stage("fetching_subtitles")
        transcript, info, transcript_source, subtitle_segments, subtitle_source = _extract_text(normalized, update_stage)
        if transcript_source == "platform_caption":
            transcript = _normalize_platform_caption_text(transcript)
        low_q, low_q_reason = _is_low_quality_transcript(transcript)
        low_signal_mode = False
        subtitle_segments = _expand_json_caption_blob_segments(subtitle_segments)
        if low_q:
            low_signal_mode = True
            if is_douyin_url(normalized):
                context_text = str(info.get("douyin_context_text") or info.get("title") or "").strip()
                if context_text:
                    transcript = (
                        "【低信号视频兜底模式】以下为可用上下文（标题/标签/文案），请据此输出结构化学习提纲：\n"
                        + context_text
                    )
                    transcript_source = "douyin_context_fallback"
            elif transcript_source not in ("douyin_context", "douyin_context_fallback"):
                transcript = _build_low_signal_fallback_text(info, transcript, subtitle_segments, low_q_reason)
                transcript_source = "low_signal_fallback"
        output_language = _detect_output_language(transcript)
        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "calling_llm"
        cfg = _load_llm_config()
        prompt = _build_prompt(
            info.get("title", "N/A"),
            info.get("duration", 0),
            transcript,
            low_signal_mode=low_signal_mode,
        )
        content = _call_chat_completion(cfg, prompt)
        parsed = _extract_json(content)
        normalized_result = apply_summary_result_enhancements(
            _normalize_result(parsed, info.get("duration", 0))
        )
        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "rendering_markdown"
        result = {
            "title": info.get("title", "N/A"),
            "uploader": info.get("uploader", ""),
            "description": info.get("description", ""),
            "tags": info.get("tags") or [],
            "url": normalized,
            "duration": info.get("duration", 0) or 0,
            "summary": normalized_result["summary"],
            "chapters": normalized_result["chapters"],
            "highlights": normalized_result["highlights"],
            "mindmap": normalized_result["mindmap"],
            "summary_sections": normalized_result.get("summary_sections") or {},
            "note_sections": normalized_result.get("note_sections") or {},
            "key_takeaways": normalized_result.get("key_takeaways") or [],
            "timeline_notes": normalized_result.get("timeline_notes") or [],
            "transcript_source": transcript_source,
            "transcript_text": transcript,
            "subtitle_source": subtitle_source if subtitle_source != "none" else transcript_source,
            "subtitle_segments": subtitle_segments,
            "transcript_quality": "low" if low_q else "normal",
            "transcript_quality_reason": low_q_reason if low_q else "",
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

        def update_stage(stage: str) -> None:
            with _TASK_LOCK:
                _TASKS[task_id]["stage"] = stage
                _TASKS[task_id]["updated_at"] = int(time.time())

        update_stage("fetching_subtitles")
        yield emit("stage", {"stage": "fetching_subtitles"})
        transcript, info, transcript_source, subtitle_segments, subtitle_source = _extract_text(normalized, update_stage)
        if transcript_source == "platform_caption":
            transcript = _normalize_platform_caption_text(transcript)
        low_q, low_q_reason = _is_low_quality_transcript(transcript)
        low_signal_mode = False

        subtitle_segments = _expand_json_caption_blob_segments(subtitle_segments)
        if low_q:
            low_signal_mode = True
            if is_douyin_url(normalized):
                context_text = str(info.get("douyin_context_text") or info.get("title") or "").strip()
                if context_text:
                    transcript = (
                        "【低信号视频兜底模式】以下为可用上下文（标题/标签/文案），请据此输出结构化学习提纲：\n"
                        + context_text
                    )
                    transcript_source = "douyin_context_fallback"
            elif transcript_source not in ("douyin_context", "douyin_context_fallback"):
                transcript = _build_low_signal_fallback_text(info, transcript, subtitle_segments, low_q_reason)
                transcript_source = "low_signal_fallback"
        output_language = _detect_output_language(transcript)

        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "calling_llm"
            _TASKS[task_id]["updated_at"] = int(time.time())
        yield emit("stage", {"stage": "calling_llm"})

        cfg = _load_llm_config()
        prompt = _build_prompt_stream_markdown(
            info.get("title", "N/A"),
            info.get("duration", 0),
            transcript,
            low_signal_mode=low_signal_mode,
        )

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

        parsed = _coerce_stream_completion_to_parsed(
            content_full, info.get("title", "N/A"), float(info.get("duration", 0) or 0)
        )
        normalized_result = apply_summary_result_enhancements(
            _normalize_result(parsed, info.get("duration", 0))
        )

        with _TASK_LOCK:
            _TASKS[task_id]["stage"] = "rendering_markdown"
            _TASKS[task_id]["updated_at"] = int(time.time())
        yield emit("stage", {"stage": "rendering_markdown"})

        result = {
            "title": info.get("title", "N/A"),
            "uploader": info.get("uploader", ""),
            "description": info.get("description", ""),
            "tags": info.get("tags") or [],
            "url": normalized,
            "duration": info.get("duration", 0) or 0,
            "summary": normalized_result["summary"],
            "chapters": normalized_result["chapters"],
            "highlights": normalized_result["highlights"],
            "mindmap": normalized_result["mindmap"],
            "summary_sections": normalized_result.get("summary_sections") or {},
            "note_sections": normalized_result.get("note_sections") or {},
            "key_takeaways": normalized_result.get("key_takeaways") or [],
            "timeline_notes": normalized_result.get("timeline_notes") or [],
            "transcript_source": transcript_source,
            "transcript_text": transcript,
            "subtitle_source": subtitle_source if subtitle_source != "none" else transcript_source,
            "subtitle_segments": subtitle_segments,
            "transcript_quality": "low" if low_q else "normal",
            "transcript_quality_reason": low_q_reason if low_q else "",
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


def _build_transcript_optimize_prompt(title: str, transcript: str) -> str:
    sample = str(transcript or "").strip()[:60000]
    return f"""
你是专业字幕校对助手。请对以下“自动转写字幕”做中文优化，目标是“可读、通顺、尽量忠实原意”。

要求：
1) 保留原始信息，不要凭空添加事实。
2) 去除明显重复口头禅、循环句和噪声词（如 music 等）。
3) 修正明显同音错字、断句问题与标点问题。
4) 保持段落结构清晰，每段 1-3 句。
5) 只输出 JSON，格式：
{{
  "cleaned_text": "优化后的完整字幕文本"
}}

视频标题：{title}
原始字幕：
{sample}
""".strip()


def optimize_task_transcript(task_id: str) -> Dict:
    task = get_summary_task(task_id)
    if task.get("status") != "completed":
        raise Exception("总结任务未完成，暂不能优化字幕")
    result = task.get("result") or {}
    transcript = str(result.get("transcript_text") or "").strip()
    if not transcript:
        raise Exception("暂无可优化字幕")

    cfg = _load_llm_config()
    prompt = _build_transcript_optimize_prompt(result.get("title") or "N/A", transcript)
    raw = _call_chat_completion(cfg, prompt).strip()

    cleaned = ""
    try:
        obj = _extract_json(raw)
        cleaned = str(obj.get("cleaned_text") or "").strip()
    except Exception:
        cleaned = _strip_chat_code_fence(raw).strip()

    if not cleaned:
        raise Exception("字幕优化失败：模型未返回有效文本")

    with _TASK_LOCK:
        task_live = _TASKS.get(task_id)
        if not task_live:
            raise Exception("任务不存在")
        live_result = task_live.get("result") or {}
        if not live_result.get("transcript_text_original"):
            live_result["transcript_text_original"] = str(live_result.get("transcript_text") or "")
        live_result["transcript_text"] = cleaned
        live_result["transcript_optimized"] = True
        task_live["result"] = live_result
        task_live["updated_at"] = int(time.time())

    return {
        "task_id": task_id,
        "transcript_text": cleaned,
        "provider": cfg.provider,
        "model": cfg.model,
        "optimized": True,
    }
