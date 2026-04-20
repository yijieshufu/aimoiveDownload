import os
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, Response

from .account_store import get_subscription
from .auth_routes import get_current_user_id
from .downloader import (
    download_video,
    extract_video_info,
    format_user_ytdlp_error,
    normalize_input_to_url,
)
from .douyin_parser import is_douyin_url, parse_douyin_url
from .usage_limits import (
    assert_can_download,
    assert_can_extract,
    check_burst,
    is_pro_subscription,
    record_download,
    record_extract,
)

router = APIRouter()

_temp_dir = os.path.join(os.getcwd(), "temp")
os.makedirs(_temp_dir, exist_ok=True)
_cookie_file_path = os.path.join(_temp_dir, "cookies.txt")


@router.post("/api/extract")
async def extract_info(request: Request):
    uid = get_current_user_id(request)
    sub = get_subscription(uid or "")
    check_burst(request, "extract")
    try:
        data = await request.json()
        url = data.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="缺少URL参数")
        assert_can_extract(request, uid, sub)
        info = extract_video_info(url)
        record_extract(request, uid, sub)
        return info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=format_user_ytdlp_error(e))


@router.post("/api/douyin/parse")
async def parse_douyin(request: Request):
    uid = get_current_user_id(request)
    sub = get_subscription(uid or "")
    check_burst(request, "douyin_parse")
    try:
        data = await request.json()
        url = data.get("url")
        normalized_url = normalize_input_to_url(url)
        if not normalized_url:
            raise HTTPException(status_code=400, detail="缺少URL参数")
        if not is_douyin_url(normalized_url):
            raise HTTPException(status_code=400, detail="仅支持抖音链接（douyin.com / iesdouyin.com）")
        assert_can_extract(request, uid, sub)
        out = parse_douyin_url(normalized_url)
        record_extract(request, uid, sub)
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=format_user_ytdlp_error(e))


@router.get("/api/download")
async def download(request: Request, url: str, format_id: str):
    uid = get_current_user_id(request)
    sub = get_subscription(uid or "")
    check_burst(request, "download")
    try:
        if not url or not format_id:
            raise HTTPException(status_code=400, detail="缺少URL或format_id参数")
        assert_can_download(request, uid, sub)
        allow_uhd = is_pro_subscription(sub)
        result = download_video(url, format_id, allow_ultra_hd=allow_uhd)
        record_download(request, uid, sub)
        return result
    except HTTPException:
        raise
    except Exception as e:
        msg = format_user_ytdlp_error(e)
        code = 403 if "Pro 专享" in msg else 400
        raise HTTPException(status_code=code, detail=msg)


@router.get("/api/download/file")
async def download_file(file_path: str):
    try:
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少 file_path 参数")

        requested_path = os.path.realpath(file_path)
        temp_root = os.path.realpath(_temp_dir)
        if not requested_path.startswith(temp_root + os.sep):
            raise HTTPException(status_code=403, detail="不允许访问 temp 目录之外的文件")

        if not os.path.exists(requested_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        return FileResponse(
            path=requested_path,
            filename=os.path.basename(requested_path),
            media_type="application/octet-stream",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/cookies/status")
async def cookies_status():
    return {"has_cookies": os.path.exists(_cookie_file_path), "path": _cookie_file_path}


@router.post("/api/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)):
    try:
        if not file:
            raise HTTPException(status_code=400, detail="缺少文件")
        content = await file.read()
        if not content or len(content) < 20:
            raise HTTPException(status_code=400, detail="cookies 文件内容为空或过短")

        text_head = content[:2000].decode("utf-8", errors="ignore")
        if "Netscape" not in text_head and "\t" not in text_head:
            raise HTTPException(status_code=400, detail="cookies 文件格式可能不正确（需要 Netscape cookies.txt）")

        with open(_cookie_file_path, "wb") as f:
            f.write(content)

        return {"ok": True, "path": _cookie_file_path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"上传 cookies 失败: {str(e)}")


def _normalize_thumb_src(src: str) -> str:
    u = (src or "").strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[len("http://") :]
    return u


def _referer_for_thumb_image(src_url: str, page_referer: Optional[str]) -> str:
    """防盗链：优先使用视频页 URL；缺省时按图床域名给合理默认值。"""
    if page_referer and page_referer.strip():
        return page_referer.strip()
    try:
        host = (urllib.parse.urlparse(src_url).hostname or "").lower()
    except Exception:
        host = ""
    if "hdslb.com" in host or "bili" in host:
        return "https://www.bilibili.com/"
    if "ytimg.com" in host or "ggpht.com" in host or "googlevideo.com" in host:
        return "https://www.youtube.com/"
    if "douyinpic" in host or "douyin.com" in host or "iesdouyin" in host:
        return "https://www.douyin.com/"
    return "https://www.bilibili.com/"


def _fetch_thumb_bytes(url: str, headers: dict) -> Tuple[bytes, str]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        content = r.read()
        content_type = r.headers.get("Content-Type") or "image/jpeg"
        return content, content_type


@router.get("/api/thumbnail")
async def proxy_thumbnail(src: str, referer: Optional[str] = None):
    if not src:
        raise HTTPException(status_code=400, detail="缺少src参数")

    try:
        src = _normalize_thumb_src(src)
        parsed = urllib.parse.urlparse(src)
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(status_code=400, detail="不支持的src协议")

        ref = _referer_for_thumb_image(src, referer)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": ref,
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
        }

        try:
            content, content_type = _fetch_thumb_bytes(src, headers)
        except HTTPError as e:
            # 旧缓存里可能仍是 maxres；代理侧再兜底一次
            if e.code == 404 and "ytimg.com" in src.lower() and "maxresdefault" in src.lower():
                alt = src.replace("maxresdefault", "hqdefault").replace("Maxresdefault", "hqdefault")
                content, content_type = _fetch_thumb_bytes(alt, headers)
            else:
                raise

        if not content:
            raise HTTPException(status_code=502, detail="封面代理返回空内容")

        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"封面代理失败: {str(e)}")
