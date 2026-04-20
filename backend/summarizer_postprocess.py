"""
总结结果后处理（可插拔层）：在 _normalize_result 之后增强导图与章节的一致性。
不修改 summarizer 核心归一逻辑，仅作为附加步骤调用。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _short_label(name: str, max_len: int = 12) -> str:
    s = (name or "").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len].rstrip() + "…"


def _normalize_text(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = re.sub(r"^[\-*•\d\.\)\(、，。\s]+", "", t)
    return t


def _short_sentence(text: str, max_len: int = 24) -> str:
    t = _normalize_text(text)
    if len(t) <= max_len:
        return t
    return t[:max_len].rstrip() + "…"


def _pick_chapter_highlights(chapter: Dict, highlights: List[Dict], limit: int = 2) -> List[str]:
    start = max(0, _to_int(chapter.get("start"), 0))
    end = max(start, _to_int(chapter.get("end"), start))
    picked: List[str] = []
    for h in highlights:
        ts = _to_int(h.get("ts"), -1)
        if ts < start or ts > end:
            continue
        txt = _short_sentence(h.get("text") or "", 24)
        if txt:
            picked.append(txt)
        if len(picked) >= limit:
            break
    return picked


def _build_chapter_story_nodes(chapter: Dict, highlights: List[Dict]) -> List[Dict]:
    title = _normalize_text(chapter.get("title") or "本章重点")
    start = max(0, _to_int(chapter.get("start"), 0))
    end = max(start, _to_int(chapter.get("end"), start))

    points = []
    for p in chapter.get("points") or []:
        s = _short_sentence(p, 24)
        if s and s not in points:
            points.append(s)
        if len(points) >= 3:
            break
    hl = _pick_chapter_highlights(chapter, highlights, limit=2)

    root_children: List[Dict] = []

    root_children.append(
        {
            "name": f"主旨：{_short_sentence(title, 18)}",
            "start": start,
            "end": end,
            "importance": 3,
            "children": [],
        }
    )

    if points:
        root_children.append(
            {
                "name": "关键要点",
                "start": start,
                "end": end,
                "importance": 3,
                "children": [
                    {
                        "name": f"要点{i + 1}：{p}",
                        "start": start,
                        "end": end,
                        "importance": 2,
                        "children": [],
                    }
                    for i, p in enumerate(points[:5])
                ],
            }
        )

    if hl:
        root_children.append(
            {
                "name": "时间证据",
                "start": start,
                "end": end,
                "importance": 2,
                "children": [
                    {
                        "name": f"证据{i + 1}：{x}",
                        "start": start,
                        "end": end,
                        "importance": 2,
                        "children": [],
                    }
                    for i, x in enumerate(hl[:4])
                ],
            }
        )

    return root_children[:6]


def align_mindmap_l1_to_chapters(mindmap_children: List[Dict], chapters: List[Dict]) -> None:
    """将一级导图节点标题与时间对齐到 chapters，减少「大纲—导图」漂移。"""
    if not mindmap_children or not chapters:
        return
    ch_sorted = sorted(chapters, key=lambda x: (x["start"], x["end"]))

    def _pick_ch_for_node(ns: int, ne: int) -> Optional[int]:
        best_i: Optional[int] = None
        best_score = -1
        for i, ch in enumerate(ch_sorted):
            cs, ce = ch["start"], ch["end"]
            overlap = max(0, min(ne, ce) - max(ns, cs))
            if overlap > best_score:
                best_score = overlap
                best_i = i
        if best_i is not None and best_score > 0:
            return best_i
        if not ch_sorted:
            return None
        return min(range(len(ch_sorted)), key=lambda i: abs(ns - ch_sorted[i]["start"]))

    for node in mindmap_children:
        ns = max(0, _to_int(node.get("start"), 0))
        ne = max(ns, _to_int(node.get("end"), ns))
        idx = _pick_ch_for_node(ns, ne)
        if idx is None:
            continue
        ch = ch_sorted[idx]
        t = str(ch.get("title") or "").strip()
        if t:
            node["name"] = _short_label(t, 12)
            node["start"] = ch["start"]
            node["end"] = ch["end"]


def _pick_chapter_by_node_range(node: Dict, chapters: List[Dict]) -> Optional[Dict]:
    if not chapters:
        return None
    ns = max(0, _to_int(node.get("start"), 0))
    ne = max(ns, _to_int(node.get("end"), ns))
    best: Optional[Dict] = None
    best_score = -1
    for ch in chapters:
        cs = max(0, _to_int(ch.get("start"), 0))
        ce = max(cs, _to_int(ch.get("end"), cs))
        overlap = max(0, min(ne, ce) - max(ns, cs))
        if overlap > best_score:
            best_score = overlap
            best = ch
    if best is not None and best_score > 0:
        return best
    return min(chapters, key=lambda ch: abs(ns - max(0, _to_int(ch.get("start"), 0))))


def apply_summary_result_enhancements(normalized: Dict) -> Dict:
    """
    对 _normalize_result 的输出做增强；就地更新 mindmap.children。
    """
    chapters = normalized.get("chapters") or []
    highlights = normalized.get("highlights") or []
    mm = normalized.get("mindmap") or {}
    children = list(mm.get("children") or [])
    if not children or not chapters:
        return normalized
    align_mindmap_l1_to_chapters(children, chapters)
    for node in children:
        chapter = _pick_chapter_by_node_range(node, chapters)
        if not chapter:
            continue
        node["children"] = _build_chapter_story_nodes(chapter, highlights)
    normalized["mindmap"] = {**mm, "children": children}
    return normalized
