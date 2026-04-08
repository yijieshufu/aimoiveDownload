import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

TEMP_DIR = os.path.join(os.getcwd(), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)
DB_PATH = os.path.join(TEMP_DIR, "workspace.db")

_LOCK = threading.Lock()
_REQUIRED_TAB_IDS = {"summary", "mindmap"}

DEFAULT_TABS = [
    {"id": "summary", "name": "Summary", "type": "system", "order_index": 0, "visible": 1},
    {"id": "chapters", "name": "Chapters", "type": "system", "order_index": 1, "visible": 1},
    {"id": "highlights", "name": "Timeline", "type": "system", "order_index": 2, "visible": 1},
    {"id": "transcript", "name": "Transcript", "type": "system", "order_index": 3, "visible": 1},
    {"id": "mindmap", "name": "Mindmap", "type": "system", "order_index": 4, "visible": 1},
    {"id": "qa", "name": "Q&A", "type": "system", "order_index": 5, "visible": 1},
]


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_workspace_store() -> None:
    with _LOCK:
        with _conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS ui_tabs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    visible INTEGER NOT NULL DEFAULT 1,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS summary_mindmap (
                    task_id TEXT PRIMARY KEY,
                    mindmap_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            count = c.execute("SELECT COUNT(*) AS n FROM ui_tabs").fetchone()["n"]
            if count == 0:
                now = int(time.time())
                for t in DEFAULT_TABS:
                    c.execute(
                        "INSERT INTO ui_tabs (id,name,type,order_index,visible,updated_at) VALUES (?,?,?,?,?,?)",
                        (t["id"], t["name"], t["type"], t["order_index"], t["visible"], now),
                    )
            c.commit()


def get_tabs() -> List[Dict]:
    init_workspace_store()
    with _LOCK:
        with _conn() as c:
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
        with _conn() as c:
            c.execute("DELETE FROM ui_tabs")
            for t in cleaned:
                c.execute(
                    "INSERT INTO ui_tabs (id,name,type,order_index,visible,updated_at) VALUES (?,?,?,?,?,?)",
                    (t["id"], t["name"], t["type"], t["order_index"], t["visible"], now),
                )
            c.commit()
    return get_tabs()


def get_mindmap(task_id: str) -> Dict:
    init_workspace_store()
    with _LOCK:
        with _conn() as c:
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


def save_mindmap(task_id: str, mindmap: Dict) -> Dict:
    init_workspace_store()
    now = int(time.time())
    mm = _sanitize_mindmap(mindmap or {})
    body = json.dumps(mm, ensure_ascii=False)
    with _LOCK:
        with _conn() as c:
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
            c.commit()
    return {"task_id": task_id, "mindmap": mm, "updated_at": now}


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

