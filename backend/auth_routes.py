import os
import time
import urllib.parse
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import BadSignature, URLSafeSerializer

from .account_store import get_subscription, get_user, init_account_store, upsert_user
from .usage_limits import build_usage_snapshot


router = APIRouter()


def _public_base_url(request: Request) -> str:
    env = os.getenv("PUBLIC_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    # best-effort fallback for local dev
    scheme = request.url.scheme
    host = request.headers.get("host") or "127.0.0.1:8003"
    return f"{scheme}://{host}"


def _serializer() -> URLSafeSerializer:
    secret = os.getenv("AUTH_SECRET_KEY", "").strip() or "dev-secret-change-me"
    return URLSafeSerializer(secret, salt="video-workbench-auth")


def _set_session_cookie(resp: RedirectResponse, user_id: str) -> None:
    s = _serializer()
    token = s.dumps({"uid": user_id, "ts": int(time.time())})
    resp.set_cookie(
        key="sid",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def get_current_user_id(request: Request) -> Optional[str]:
    raw = request.cookies.get("sid") or ""
    if not raw:
        return None
    s = _serializer()
    try:
        data = s.loads(raw)
        return str((data or {}).get("uid") or "").strip() or None
    except BadSignature:
        return None
    except Exception:
        return None


def require_env(*keys: str) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少 OAuth 配置: {', '.join(missing)}")


def _github_oauth_urls() -> Dict[str, str]:
    return {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "user": "https://api.github.com/user",
    }


def _google_oauth_urls() -> Dict[str, str]:
    return {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "user": "https://www.googleapis.com/oauth2/v2/userinfo",
    }


def _wechat_oauth_urls() -> Dict[str, str]:
    return {
        "authorize": "https://open.weixin.qq.com/connect/qrconnect",
        "token": "https://api.weixin.qq.com/sns/oauth2/access_token",
        "user": "https://api.weixin.qq.com/sns/userinfo",
    }


@router.get("/api/auth/login/{provider}")
async def auth_login(provider: str, request: Request, next: str = "/frontend/"):
    init_account_store()
    p = (provider or "").strip().lower()
    next_url = next if next.startswith("/") else "/frontend/"
    s = _serializer()
    state = s.dumps({"p": p, "next": next_url, "ts": int(time.time())})
    base = _public_base_url(request)
    redirect_uri = f"{base}/api/auth/callback/{p}"

    if p == "github":
        require_env("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET")
        u = _github_oauth_urls()
        q = {
            "client_id": os.getenv("GITHUB_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        return RedirectResponse(u["authorize"] + "?" + urllib.parse.urlencode(q))

    if p == "google":
        require_env("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
        u = _google_oauth_urls()
        q = {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return RedirectResponse(u["authorize"] + "?" + urllib.parse.urlencode(q))

    if p == "wechat":
        require_env("WECHAT_APP_ID", "WECHAT_APP_SECRET")
        u = _wechat_oauth_urls()
        q = {
            "appid": os.getenv("WECHAT_APP_ID"),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }
        return RedirectResponse(u["authorize"] + "?" + urllib.parse.urlencode(q) + "#wechat_redirect")

    raise HTTPException(status_code=404, detail="unknown provider")


@router.get("/api/auth/callback/{provider}")
async def auth_callback(provider: str, request: Request, code: str = "", state: str = ""):
    init_account_store()
    p = (provider or "").strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    if not state:
        raise HTTPException(status_code=400, detail="missing state")

    s = _serializer()
    try:
        st = s.loads(state)
    except BadSignature:
        raise HTTPException(status_code=400, detail="invalid state")

    next_url = str((st or {}).get("next") or "/frontend/").strip()
    base = _public_base_url(request)
    redirect_uri = f"{base}/api/auth/callback/{p}"

    async with httpx.AsyncClient(timeout=20) as client:
        if p == "github":
            require_env("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET")
            u = _github_oauth_urls()
            token_resp = await client.post(
                u["token"],
                data={
                    "client_id": os.getenv("GITHUB_CLIENT_ID"),
                    "client_secret": os.getenv("GITHUB_CLIENT_SECRET"),
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            tok = token_resp.json()
            access_token = tok.get("access_token") or ""
            if not access_token:
                raise HTTPException(status_code=400, detail="github token exchange failed")
            user_resp = await client.get(u["user"], headers={"Authorization": f"Bearer {access_token}"})
            profile = user_resp.json()
            uid = str(profile.get("id") or "")
            user = upsert_user("github", uid, profile)
            resp = RedirectResponse(next_url)
            _set_session_cookie(resp, user["id"])
            return resp

        if p == "google":
            require_env("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
            u = _google_oauth_urls()
            token_resp = await client.post(
                u["token"],
                data={
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            tok = token_resp.json()
            access_token = tok.get("access_token") or ""
            if not access_token:
                raise HTTPException(status_code=400, detail="google token exchange failed")
            user_resp = await client.get(u["user"], headers={"Authorization": f"Bearer {access_token}"})
            profile = user_resp.json()
            uid = str(profile.get("id") or profile.get("sub") or "")
            user = upsert_user("google", uid, profile)
            resp = RedirectResponse(next_url)
            _set_session_cookie(resp, user["id"])
            return resp

        if p == "wechat":
            require_env("WECHAT_APP_ID", "WECHAT_APP_SECRET")
            u = _wechat_oauth_urls()
            token_resp = await client.get(
                u["token"],
                params={
                    "appid": os.getenv("WECHAT_APP_ID"),
                    "secret": os.getenv("WECHAT_APP_SECRET"),
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            tok = token_resp.json()
            access_token = tok.get("access_token") or ""
            openid = tok.get("openid") or ""
            if not access_token or not openid:
                raise HTTPException(status_code=400, detail="wechat token exchange failed")
            user_resp = await client.get(u["user"], params={"access_token": access_token, "openid": openid})
            profile = user_resp.json()
            uid = str(profile.get("openid") or openid)
            user = upsert_user("wechat", uid, profile)
            resp = RedirectResponse(next_url)
            _set_session_cookie(resp, user["id"])
            return resp

    raise HTTPException(status_code=404, detail="unknown provider")


@router.post("/api/auth/logout")
async def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sid", path="/")
    return resp


@router.get("/api/me")
async def api_me(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        sub = {"plan": "free", "pro_until": None}
        return {
            "user": None,
            "subscription": sub,
            "plan": "free",
            "usage": build_usage_snapshot(request, None, None),
        }
    user = get_user(uid)
    sub = get_subscription(uid)
    return {
        "user": user,
        "subscription": sub,
        "plan": sub.get("plan") or "free",
        "usage": build_usage_snapshot(request, uid, sub),
    }
