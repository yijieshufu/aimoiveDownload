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
from typing import Dict, List, Optional

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
    if len(summary) > 12:
        summary = summary[:12]

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

    return {
        "summary": summary,
        "chapters": chapters,
        "highlights": highlights[:30],
        "mindmap": mindmap,
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
            "transcript_source": transcript_source,
            "transcript_text": transcript,
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
    task_id = uuid.uuid4().hex
    with _TASK_LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "stage": "pending",
            "error": None,
            "result": None,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
    t = threading.Thread(target=_run_task, args=(task_id, url), daemon=True)
    t.start()
    return task_id


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
