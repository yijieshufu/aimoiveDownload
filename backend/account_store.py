import threading
import time
import uuid
from typing import Dict, Optional

from .database import get_db, init_db

_LOCK = threading.Lock()


def init_account_store() -> None:
    """与 workspace 共用 init_db，保留函数名以兼容既有调用。"""
    init_db()


def upsert_user(provider: str, provider_user_id: str, profile: Dict) -> Dict:
    init_account_store()
    now = int(time.time())
    provider = (provider or "").strip().lower()
    provider_user_id = str(provider_user_id or "").strip()
    if not provider or not provider_user_id:
        raise Exception("invalid provider user")

    email = (profile or {}).get("email")
    name = (profile or {}).get("name") or (profile or {}).get("login") or ""
    avatar_url = (profile or {}).get("avatar_url") or ""

    with _LOCK:
        with get_db() as c:
            row = c.execute(
                "SELECT id FROM users WHERE provider=? AND provider_user_id=?",
                (provider, provider_user_id),
            ).fetchone()
            if row:
                uid = row["id"]
                c.execute(
                    """
                    UPDATE users SET email=?, name=?, avatar_url=?, updated_at=?
                    WHERE id=?
                    """,
                    (email, name, avatar_url, now, uid),
                )
            else:
                uid = uuid.uuid4().hex
                c.execute(
                    """
                    INSERT INTO users (id, provider, provider_user_id, email, name, avatar_url, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (uid, provider, provider_user_id, email, name, avatar_url, now, now),
                )
    return get_user(uid) or {"id": uid}


def get_user(user_id: str) -> Optional[Dict]:
    init_account_store()
    uid = str(user_id or "").strip()
    if not uid:
        return None
    with _LOCK:
        with get_db() as c:
            row = c.execute(
                "SELECT id, provider, provider_user_id, email, name, avatar_url, created_at, updated_at FROM users WHERE id=?",
                (uid,),
            ).fetchone()
    if not row:
        return None
    return dict(row)


def get_subscription(user_id: str) -> Dict:
    init_account_store()
    uid = str(user_id or "").strip()
    if not uid:
        return {"plan": "free", "pro_until": None}
    with _LOCK:
        with get_db() as c:
            row = c.execute(
                "SELECT plan, pro_until, updated_at FROM subscriptions WHERE user_id=?",
                (uid,),
            ).fetchone()
    if not row:
        return {"plan": "free", "pro_until": None}
    return {"plan": row["plan"], "pro_until": row["pro_until"], "updated_at": row["updated_at"]}


def set_subscription_plan(user_id: str, plan: str, pro_until: Optional[int] = None) -> Dict:
    init_account_store()
    uid = str(user_id or "").strip()
    if not uid:
        raise Exception("missing user_id")
    plan = (plan or "free").strip().lower()
    now = int(time.time())
    with _LOCK:
        with get_db() as c:
            c.execute(
                """
                INSERT INTO subscriptions (user_id, plan, pro_until, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                  plan=excluded.plan,
                  pro_until=excluded.pro_until,
                  updated_at=excluded.updated_at
                """,
                (uid, plan, pro_until, now),
            )
    return get_subscription(uid)


def create_order(user_id: str, channel: str, amount: int, title: str = "升级 Pro") -> Dict:
    init_account_store()
    uid = str(user_id or "").strip()
    if not uid:
        raise Exception("missing user_id")
    channel = (channel or "").strip().lower()
    if channel not in {"wechatpay", "alipay"}:
        raise Exception("channel must be wechatpay or alipay")
    n_amount = int(amount or 0)
    if n_amount <= 0:
        raise Exception("amount must be positive")
    now = int(time.time())
    oid = uuid.uuid4().hex
    with _LOCK:
        with get_db() as c:
            c.execute(
                """
                INSERT INTO orders (id, user_id, channel, amount, currency, status, title, created_at)
                VALUES (?,?,?,?, 'CNY', 'created', ?, ?)
                """,
                (oid, uid, channel, n_amount, title, now),
            )
    return get_order(oid) or {"id": oid}


def get_order(order_id: str) -> Optional[Dict]:
    init_account_store()
    oid = str(order_id or "").strip()
    if not oid:
        return None
    with _LOCK:
        with get_db() as c:
            row = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    return dict(row) if row else None


def mark_order_paid(order_id: str, provider_trade_no: str = "") -> Dict:
    init_account_store()
    oid = str(order_id or "").strip()
    if not oid:
        raise Exception("missing order_id")
    now = int(time.time())
    with _LOCK:
        with get_db() as c:
            c.execute(
                """
                UPDATE orders SET status='paid', provider_trade_no=?, paid_at=?
                WHERE id=?
                """,
                (provider_trade_no or "", now, oid),
            )
    return get_order(oid) or {"id": oid}
