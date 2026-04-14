"""
统一 SQLite 入口：路径、WAL、初始化与旧库迁移（原 temp/workspace.db -> backend/data/app.db）。
"""
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "data", "app.db")


def get_db_path() -> str:
    override = os.getenv("DATABASE_PATH", "").strip()
    path = os.path.abspath(override) if override else _DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _legacy_workspace_db() -> str:
    return os.path.join(os.getcwd(), "temp", "workspace.db")


def _maybe_migrate_legacy() -> None:
    """
    若新库不存在或为空文件，且存在旧版 temp/workspace.db，则整库复制一次，避免静默丢数据。
    """
    target = get_db_path()
    legacy = _legacy_workspace_db()
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return
    if os.path.exists(legacy) and os.path.getsize(legacy) > 0:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(legacy, target)


@contextmanager
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_DEFAULT_TABS = [
    ("summary", "AI笔记", "system", 0, 1),
    ("highlights", "时间笔记", "system", 1, 1),
    ("transcript", "字幕稿", "system", 2, 1),
    ("mindmap", "思维导图", "system", 3, 1),
    ("qa", "问答", "system", 4, 1),
]


def init_db() -> None:
    _maybe_migrate_legacy()
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                email TEXT,
                name TEXT,
                avatar_url TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(provider, provider_user_id)
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id TEXT PRIMARY KEY,
                plan TEXT NOT NULL,
                pro_until INTEGER,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                status TEXT NOT NULL,
                title TEXT,
                provider_trade_no TEXT,
                created_at INTEGER NOT NULL,
                paid_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS ui_tabs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                visible INTEGER NOT NULL DEFAULT 1,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS summary_mindmap (
                task_id TEXT PRIMARY KEY,
                mindmap_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS summary_chat (
                task_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (task_id, seq)
            );

            CREATE TABLE IF NOT EXISTS summary_edit (
                task_id TEXT PRIMARY KEY,
                sections_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS usage_daily (
                key TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            );
            """
        )
        conn.execute("DELETE FROM ui_tabs WHERE id IN (?, ?)", ("chapters", "note"))
        now = int(time.time())
        count = conn.execute("SELECT COUNT(*) AS n FROM ui_tabs").fetchone()["n"]
        if count == 0:
            for tid, name, typ, order_idx, vis in _DEFAULT_TABS:
                conn.execute(
                    "INSERT INTO ui_tabs (id,name,type,order_index,visible,updated_at) VALUES (?,?,?,?,?,?)",
                    (tid, name, typ, order_idx, vis, now),
                )
        else:
            # 兼容旧库：新增默认 system tab 时，自动补齐缺失项（不覆盖用户自定义顺序/可见性）。
            for tid, name, typ, order_idx, vis in _DEFAULT_TABS:
                row = conn.execute("SELECT id FROM ui_tabs WHERE id=?", (tid,)).fetchone()
                if row:
                    continue
                conn.execute(
                    "INSERT INTO ui_tabs (id,name,type,order_index,visible,updated_at) VALUES (?,?,?,?,?,?)",
                    (tid, name, typ, order_idx, vis, now),
                )
