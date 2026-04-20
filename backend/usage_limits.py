"""
按日统计的轻量额度：登录用户按 user_id，未登录按 IP 哈希。
Pro 用户在订阅有效期内跳过额度（仍可能受 burst 限流约束）。
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import Request

from .database import get_db

# 每日上限（Pro 不计入）
LIMIT_ANON_EXTRACT = 12
LIMIT_ANON_DOWNLOAD = 8
LIMIT_FREE_EXTRACT = 35
LIMIT_FREE_DOWNLOAD = 35
LIMIT_FREE_SUMMARIZE = 5

_BURST_MAX_PER_MINUTE = 22
_burst_minute: Dict[str, int] = {}


def _dev_allow_anonymous_summarize() -> bool:
    """开发期匿名总结：显式 0/false 关闭；显式 1 开启；未配置时在非生产环境默认开启（按 IP 日限额）。"""
    v = (os.getenv("DEV_ALLOW_ANONYMOUS_AI") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    if _is_production_env():
        return False
    return True


def _dev_anon_summarize_daily_limit() -> int:
    raw = (os.getenv("DEV_ANON_SUMMARIZE_DAILY") or "").strip()
    if not raw:
        return 50
    try:
        n = int(raw)
        return max(1, n)
    except ValueError:
        return 50


def _is_production_env() -> bool:
    prod = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("APP_ENV") or "").strip().lower()
    return prod in ("production", "prod")


def _dev_bypass_extract_download_limits() -> bool:
    """非生产环境默认不统计解析/下载日额度，便于本地开发；生产环境始终限制。

    本地若要模拟额度：设置 DEV_BYPASS_EXTRACT_DOWNLOAD=0
    """
    if _is_production_env():
        return False
    v = (os.getenv("DEV_BYPASS_EXTRACT_DOWNLOAD") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    return True


def _today_ymd() -> str:
    return time.strftime("%Y%m%d", time.localtime())


def client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def ip_fingerprint(request: Request) -> str:
    raw = client_ip(request)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def usage_key(action: str, user_id: Optional[str], fp: str, day: str) -> str:
    if user_id:
        return f"{action}:u:{user_id}:{day}"
    return f"{action}:i:{fp}:{day}"


def is_pro_subscription(sub: Optional[Dict[str, Any]]) -> bool:
    if not sub:
        return False
    plan = str(sub.get("plan") or "").lower()
    if plan not in ("pro", "premium"):
        return False
    until = sub.get("pro_until")
    if until is None:
        return True
    try:
        return int(until) > int(time.time())
    except (TypeError, ValueError):
        return False


def _get_count(key: str) -> int:
    with get_db() as conn:
        row = conn.execute("SELECT count FROM usage_daily WHERE key=?", (key,)).fetchone()
    return int(row["count"]) if row else 0


def _incr_count(key: str) -> int:
    now = int(time.time())
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO usage_daily (key, count, updated_at) VALUES (?, 1, ?)
            ON CONFLICT(key) DO UPDATE SET
              count = usage_daily.count + 1,
              updated_at = excluded.updated_at
            """,
            (key, now),
        )
        row = conn.execute("SELECT count FROM usage_daily WHERE key=?", (key,)).fetchone()
    return int(row["count"]) if row else 1


def check_burst(request: Request, route: str) -> None:
    """按自然分钟桶限制每 IP 请求次数，防止脚本刷爆。"""
    fp = ip_fingerprint(request)
    minute = int(time.time()) // 60
    bucket = f"{route}:{fp}:{minute}"
    n = _burst_minute.get(bucket, 0)
    if n >= _BURST_MAX_PER_MINUTE:
        from fastapi import HTTPException

        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    _burst_minute[bucket] = n + 1
    if len(_burst_minute) > 8000:
        for k in list(_burst_minute.keys()):
            try:
                m = int(str(k).rsplit(":", 1)[-1])
            except ValueError:
                _burst_minute.pop(k, None)
                continue
            if m < minute - 3:
                _burst_minute.pop(k, None)


def _limits_for(user_id: Optional[str], pro: bool) -> Tuple[int, int, int]:
    if pro:
        return 99999, 99999, 99999
    if user_id:
        return LIMIT_FREE_EXTRACT, LIMIT_FREE_DOWNLOAD, LIMIT_FREE_SUMMARIZE
    return LIMIT_ANON_EXTRACT, LIMIT_ANON_DOWNLOAD, 0


def assert_can_extract(request: Request, user_id: Optional[str], sub: Optional[Dict[str, Any]]) -> None:
    if _dev_bypass_extract_download_limits():
        return
    pro = is_pro_subscription(sub)
    lim_ext, _, _ = _limits_for(user_id, pro)
    if pro:
        return
    day = _today_ymd()
    key = usage_key("extract", user_id, ip_fingerprint(request), day)
    if _get_count(key) >= lim_ext:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=402,
            detail="今日解析次数已达上限，请登录以提升额度或升级 Pro。",
        )


def record_extract(request: Request, user_id: Optional[str], sub: Optional[Dict[str, Any]]) -> None:
    if _dev_bypass_extract_download_limits():
        return
    if is_pro_subscription(sub):
        return
    day = _today_ymd()
    key = usage_key("extract", user_id, ip_fingerprint(request), day)
    _incr_count(key)


def assert_can_download(request: Request, user_id: Optional[str], sub: Optional[Dict[str, Any]]) -> None:
    if _dev_bypass_extract_download_limits():
        return
    pro = is_pro_subscription(sub)
    _, lim_dl, _ = _limits_for(user_id, pro)
    if pro:
        return
    day = _today_ymd()
    key = usage_key("download", user_id, ip_fingerprint(request), day)
    if _get_count(key) >= lim_dl:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=402,
            detail="今日下载次数已达上限，请登录以提升额度或升级 Pro。",
        )


def record_download(request: Request, user_id: Optional[str], sub: Optional[Dict[str, Any]]) -> None:
    if _dev_bypass_extract_download_limits():
        return
    if is_pro_subscription(sub):
        return
    day = _today_ymd()
    key = usage_key("download", user_id, ip_fingerprint(request), day)
    _incr_count(key)


def assert_can_summarize(request: Request, user_id: Optional[str], sub: Optional[Dict[str, Any]]) -> None:
    from fastapi import HTTPException

    pro = is_pro_subscription(sub)
    day = _today_ymd()
    fp = ip_fingerprint(request)

    if not user_id:
        if _dev_allow_anonymous_summarize():
            if pro:
                return
            lim = _dev_anon_summarize_daily_limit()
            key = usage_key("summarize", None, fp, day)
            if _get_count(key) >= lim:
                raise HTTPException(
                    status_code=402,
                    detail="今日 AI 总结次数已达上限（开发匿名额度），请登录或明日再试。",
                )
            return
        raise HTTPException(status_code=401, detail="请先登录后再使用 AI 视频总结")

    _, _, lim_sum = _limits_for(user_id, pro)
    if pro:
        return
    key = usage_key("summarize", user_id, fp, day)
    if _get_count(key) >= lim_sum:
        raise HTTPException(
            status_code=402,
            detail="今日 AI 总结次数已达上限，请升级 Pro 解除限制。",
        )


def record_summarize(request: Request, user_id: Optional[str], sub: Optional[Dict[str, Any]]) -> None:
    if is_pro_subscription(sub):
        return
    day = _today_ymd()
    fp = ip_fingerprint(request)
    if not user_id:
        if _dev_allow_anonymous_summarize():
            key = usage_key("summarize", None, fp, day)
            _incr_count(key)
        return
    key = usage_key("summarize", user_id, fp, day)
    _incr_count(key)


def build_usage_snapshot(request: Request, user_id: Optional[str], sub: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    pro = is_pro_subscription(sub)
    day = _today_ymd()
    fp = ip_fingerprint(request)
    lim_ext, lim_dl, lim_sum = _limits_for(user_id, pro)
    bypass_ed = _dev_bypass_extract_download_limits()

    def left(action: str, lim: int) -> Optional[int]:
        if pro or lim >= 90000:
            return None
        k = usage_key(action, user_id, fp, day)
        used = _get_count(k)
        return max(0, lim - used)

    if pro or bypass_ed:
        ext_left = None
        dl_left = None
    else:
        ext_left = left("extract", lim_ext)
        dl_left = left("download", lim_dl)
    if user_id:
        sum_left = left("summarize", lim_sum)
    elif _dev_allow_anonymous_summarize() and not pro:
        sum_left = left("summarize", _dev_anon_summarize_daily_limit())
    else:
        sum_left = None

    parts = []
    if ext_left is not None:
        parts.append(f"解析剩余 {ext_left}")
    if dl_left is not None:
        parts.append(f"下载剩余 {dl_left}")
    if sum_left is not None:
        parts.append(f"AI总结剩余 {sum_left}")
    hint = " · ".join(parts) if parts else ("Pro 畅享额度" if pro else "")

    return {
        "pro": pro,
        "extract_remaining": ext_left,
        "download_remaining": dl_left,
        "summarize_remaining": sum_left,
        "hint": hint,
    }
