import json
import threading
import time
from typing import Dict, List, Optional

from .database import get_db, init_db

_LOCK = threading.Lock()
_REQUIRED_TAB_IDS = {"summary", "mindmap"}

DEFAULT_TABS = [
    {"id": "summary", "name": "摘要", "type": "system", "order_index": 0, "visible": 1},
    {"id": "highlights", "name": "时间轴", "type": "system", "order_index": 1, "visible": 1},
    {"id": "transcript", "name": "字幕稿", "type": "system", "order_index": 2, "visible": 1},
    {"id": "mindmap", "name": "思维导图", "type": "system", "order_index": 3, "visible": 1},
    {"id": "qa", "name": "问答", "type": "system", "order_index": 4, "visible": 1},
]


def init_workspace_store() -> None:
    """与 account 共用 init_db，保留函数名以兼容既有调用。"""
    init_db()


def get_tabs() -> List[Dict]:
    init_workspace_store()
    with _LOCK:
        with get_db() as c:
            rows = c.execute(
                "SELECT id,name,type,order_index,visible FROM ui_tabs ORDER BY order_index ASC, id ASC"
            ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "order_index": r["order_index"],
            "visible": bool(r["visible"]),
        }
        for r in rows
    ]


def save_tabs(tabs: List[Dict]) -> List[Dict]:
    init_workspace_store()
    now = int(time.time())
    cleaned = []
    for idx, t in enumerate(tabs or []):
        tid = str(t.get("id") or "").strip()
        name = str(t.get("name") or "").strip()
        if not tid or not name:
            continue
        cleaned.append(
            {
                "id": tid,
                "name": name,
                "type": str(t.get("type") or "custom"),
                "order_index": int(t.get("order_index", idx)),
                "visible": 1 if bool(t.get("visible", True)) else 0,
            }
        )
    if not cleaned:
        raise Exception("tabs payload is empty")

    by_id = {x["id"]: x for x in cleaned}
    for base in DEFAULT_TABS:
        if base["id"] in _REQUIRED_TAB_IDS and base["id"] not in by_id:
            by_id[base["id"]] = {
                "id": base["id"],
                "name": base["name"],
                "type": "system",
                "order_index": base["order_index"],
                "visible": 1,
            }
    cleaned = sorted(by_id.values(), key=lambda x: int(x.get("order_index", 0)))
    cleaned = [{**t, "order_index": i, "visible": 1 if t["id"] in _REQUIRED_TAB_IDS else t.get("visible", 1)} for i, t in enumerate(cleaned)]

    with _LOCK:
        with get_db() as c:
            c.execute("DELETE FROM ui_tabs")
            for t in cleaned:
                c.execute(
                    "INSERT INTO ui_tabs (id,name,type,order_index,visible,updated_at) VALUES (?,?,?,?,?,?)",
                    (t["id"], t["name"], t["type"], t["order_index"], t["visible"], now),
                )
    return get_tabs()


def get_mindmap(task_id: str) -> Dict:
    init_workspace_store()
    with _LOCK:
        with get_db() as c:
            row = c.execute(
                "SELECT mindmap_json,updated_at FROM summary_mindmap WHERE task_id=?",
                (task_id,),
            ).fetchone()
    if not row:
        return {"task_id": task_id, "mindmap": None, "updated_at": None}
    return {
        "task_id": task_id,
        "mindmap": json.loads(row["mindmap_json"]),
        "updated_at": row["updated_at"],
    }


def _sanitize_summary_sections(raw: Dict) -> Dict:
    def clip_str(s: str, max_len: int) -> str:
        t = str(s or "").strip()
        return t[:max_len]

    def clip_list(arr, max_items: int, max_item_len: int) -> List[str]:
        out = []
        if not isinstance(arr, list):
            return out
        for x in arr[:max_items]:
            t = clip_str(x, max_item_len)
            if t:
                out.append(t)
        return out

    d = raw if isinstance(raw, dict) else {}
    return {
        "overview": clip_list(d.get("overview") or [], 24, 2000),
        "outline": clip_list(d.get("outline") or [], 40, 500),
        "key_points": clip_list(d.get("key_points") or [], 40, 2000),
        "one_liner": clip_str(d.get("one_liner") or "", 2000),
    }


def get_summary_edit(task_id: str) -> Optional[Dict]:
    init_workspace_store()
    with _LOCK:
        with get_db() as c:
            row = c.execute(
                "SELECT sections_json,updated_at FROM summary_edit WHERE task_id=?",
                (task_id,),
            ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["sections_json"])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {"sections": _sanitize_summary_sections(data), "updated_at": row["updated_at"]}


def save_summary_edit(task_id: str, sections: Dict) -> Dict:
    init_workspace_store()
    now = int(time.time())
    cleaned = _sanitize_summary_sections(sections or {})
    body = json.dumps(cleaned, ensure_ascii=False)
    with _LOCK:
        with get_db() as c:
            c.execute(
                """
                INSERT INTO summary_edit (task_id,sections_json,updated_at)
                VALUES (?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                  sections_json=excluded.sections_json,
                  updated_at=excluded.updated_at
                """,
                (task_id, body, now),
            )
    return {"task_id": task_id, "sections": cleaned, "updated_at": now}


def delete_summary_edit(task_id: str) -> None:
    init_workspace_store()
    with _LOCK:
        with get_db() as c:
            c.execute("DELETE FROM summary_edit WHERE task_id=?", (task_id,))


def save_mindmap(task_id: str, mindmap: Dict) -> Dict:
    init_workspace_store()
    now = int(time.time())
    mm = _sanitize_mindmap(mindmap or {})
    body = json.dumps(mm, ensure_ascii=False)
    with _LOCK:
        with get_db() as c:
            c.execute(
                """
                INSERT INTO summary_mindmap (task_id,mindmap_json,updated_at)
                VALUES (?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                  mindmap_json=excluded.mindmap_json,
                  updated_at=excluded.updated_at
                """,
                (task_id, body, now),
            )
    return {"task_id": task_id, "mindmap": mm, "updated_at": now}


def append_chat_message(task_id: str, role: str, content: str) -> Dict:
    init_workspace_store()
    role = (role or "").strip().lower()
    if role not in {"user", "assistant", "system"}:
        role = "user"
    text = str(content or "").strip()
    if not text:
        raise Exception("content is empty")
    now = int(time.time())
    with _LOCK:
        with get_db() as c:
            row = c.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM summary_chat WHERE task_id=?",
                (task_id,),
            ).fetchone()
            seq = int(row["m"] or 0) + 1
            c.execute(
                "INSERT INTO summary_chat (task_id,seq,role,content,created_at) VALUES (?,?,?,?,?)",
                (task_id, seq, role, text, now),
            )
    return {"task_id": task_id, "seq": seq, "role": role, "content": text, "created_at": now}


def get_chat_messages(task_id: str, limit: int = 30) -> List[Dict]:
    init_workspace_store()
    lim = max(1, min(200, int(limit or 30)))
    with _LOCK:
        with get_db() as c:
            rows = c.execute(
                "SELECT seq,role,content,created_at FROM summary_chat WHERE task_id=? ORDER BY seq ASC LIMIT ?",
                (task_id, lim),
            ).fetchall()
    return [
        {"seq": r["seq"], "role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        for r in rows
    ]


def _sanitize_mindmap(mindmap: Dict) -> Dict:
    title = str((mindmap or {}).get("title") or "Video Topic").strip()[:40] or "Video Topic"
    seq = {"v": 0}

    def is_bad_name(name: str) -> bool:
        s = str(name or "").strip()
        if not s:
            return True
        stripped = s.replace(" ", "")
        return stripped in {"(", ")", "{", "}", "[]", "[", "]", "（）", "{}", "[]"}

    def clean_node(node: Dict, depth: int) -> Optional[Dict]:
        if depth > 4 or not isinstance(node, dict):
            return None
        name = str(node.get("name") or node.get("title") or "").strip()
        if is_bad_name(name):
            name = ""
        children = []
        for c in node.get("children") or []:
            cc = clean_node(c, depth + 1)
            if cc:
                children.append(cc)
        if not name and not children:
            return None
        if not name:
            name = "Node"
        seq["v"] += 1
        return {
            "id": str(node.get("id") or f"n{seq['v']}"),
            "name": name[:40],
            "start": int(node.get("start") or 0),
            "end": int(node.get("end") or 0),
            "importance": max(1, min(5, int(node.get("importance") or 3))),
            "children": children[:8],
        }

    children = []
    seen = set()
    for n in (mindmap or {}).get("children") or []:
        cn = clean_node(n, 1)
        if not cn:
            continue
        key = cn["name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        children.append(cn)
    return {"title": title, "children": children[:8]}
