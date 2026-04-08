import json
import os
import re
import urllib.parse
import urllib.request
import http.cookiejar
from typing import Dict, Optional

temp_dir = os.path.join(os.getcwd(), "temp")
cookie_file_path = os.path.join(temp_dir, "cookies.txt")

_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))


def is_douyin_url(url: str) -> bool:
    lowered = (url or "").lower()
    return ("douyin.com" in lowered) or ("iesdouyin.com" in lowered)


def _load_cookie_header_for_douyin() -> str:
    if not os.path.exists(cookie_file_path):
        return ""
    pairs: list[str] = []
    try:
        with open(cookie_file_path, "r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _, path, _, _, name, value = parts[:7]
                if ("douyin.com" in domain) or ("iesdouyin.com" in domain):
                    if name and value:
                        pairs.append(f"{name}={value}")
    except Exception:
        return ""
    return "; ".join(pairs)


def _default_headers(referer: str = "https://www.douyin.com/") -> Dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "application/json,text/plain,*/*",
    }
    cookie_header = _load_cookie_header_for_douyin()
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def _http_get_json(url: str, headers: Optional[Dict] = None) -> Dict:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with _opener.open(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    if not raw.strip():
        raise Exception("抖音接口返回空数据")
    return json.loads(raw)


def _http_get_text(url: str, headers: Optional[Dict] = None) -> str:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with _opener.open(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _resolve_redirect_url(url: str) -> str:
    req = urllib.request.Request(url, headers=_default_headers(), method="GET")
    with _opener.open(req, timeout=20) as resp:
        return resp.geturl()


def _extract_douyin_video_id(url: str) -> str:
    resolved = _resolve_redirect_url(url)
    m = re.search(r"/video/(\d+)", resolved)
    if m:
        return m.group(1)
    m2 = re.search(r"modal_id=(\d+)", resolved)
    if m2:
        return m2.group(1)
    raise Exception("无法从抖音链接中提取 video_id")


def _decode_js_escaped_url(value: str) -> str:
    if not value:
        return ""
    return (
        value.replace("\\u002F", "/")
        .replace("\\/", "/")
        .replace("\\u0026", "&")
    )


def _decode_json_escaped_text(value: str) -> str:
    if not value:
        return ""
    try:
        # 兼容 \\u4e2d\\u6587 与普通 UTF-8 文本
        return json.loads(f'"{value}"')
    except Exception:
        return value


def _extract_item_from_share_page(video_id: str) -> Dict:
    """
    公开分享页兜底解析（无登录态）：
    从 iesdouyin 分享页 HTML 中提取 playwm / 标题 / 作者等字段。
    """
    share_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    mobile_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
        "Mobile/15E148 Safari/604.1"
    )
    html = _http_get_text(
        share_url,
        headers=_default_headers("https://www.iesdouyin.com/") | {"User-Agent": mobile_ua},
    )

    m_playwm = re.search(
        r'"url_list":\["(https:\\u002F\\u002F[^"]*playwm[^"]*)"\]',
        html,
    )
    if not m_playwm:
        raise Exception("公开分享页中未找到 playwm 地址")
    playwm_url = _decode_js_escaped_url(m_playwm.group(1))

    m_cover = re.search(
        r'"cover":\{.*?"url_list":\["(https:\\u002F\\u002F[^"]+)"\]',
        html,
        flags=re.DOTALL,
    )
    cover_url = _decode_js_escaped_url(m_cover.group(1)) if m_cover else ""
    if not cover_url:
        m_cover_fallback = re.search(r'(https:\\u002F\\u002F[^"]*douyinpic\.com[^"]*)', html)
        if m_cover_fallback:
            cover_url = _decode_js_escaped_url(m_cover_fallback.group(1))
    m_desc = re.search(r'"desc":"([^"]*)"', html)
    m_nickname = re.search(r'"nickname":"([^"]*)"', html)
    m_width = re.search(r'"width":(\d+)', html)
    m_height = re.search(r'"height":(\d+)', html)
    m_duration = re.search(r'"duration":(\d+)', html)

    return {
        "desc": _decode_json_escaped_text(m_desc.group(1) if m_desc else "N/A"),
        "author": {"nickname": _decode_json_escaped_text(m_nickname.group(1) if m_nickname else "N/A")},
        "video": {
            "width": int(m_width.group(1)) if m_width else 0,
            "height": int(m_height.group(1)) if m_height else 0,
            "duration": int(m_duration.group(1)) * 1000 if m_duration else 0,
            "cover": {"url_list": [cover_url] if cover_url else []},
            "play_addr": {"url_list": [playwm_url]},
        },
        "statistics": {"play_count": 0},
    }


def get_douyin_item_info(url: str) -> Dict:
    video_id = _extract_douyin_video_id(url)
    api = f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={video_id}"
    try:
        data = _http_get_json(api, headers=_default_headers("https://www.douyin.com/"))
        items = data.get("item_list") or []
        if items:
            return items[0]
    except Exception:
        pass
    # 公开 API 空返回时，回退公开分享页抓取（仍不需要登录态）
    return _extract_item_from_share_page(video_id)


def _get_first_url_from_addr(addr: Dict) -> str:
    if not addr:
        return ""
    urls = addr.get("url_list") or []
    return urls[0] if urls else ""


def build_douyin_nowm_url(item: Dict) -> str:
    video = item.get("video") or {}
    play_addr_url = _get_first_url_from_addr(video.get("play_addr") or {})
    download_addr_url = _get_first_url_from_addr(video.get("download_addr") or {})
    candidate = play_addr_url or download_addr_url
    if not candidate:
        raise Exception("未找到抖音视频播放地址")
    return candidate.replace("playwm", "play")


def _probe_content_length(url: str) -> int:
    """
    尝试探测直链文件大小（字节）。
    优先 HEAD；若不返回长度，则使用 Range: bytes=0-0 回退。
    """
    headers = _default_headers("https://www.douyin.com/")
    try:
        req = urllib.request.Request(url, headers=headers, method="HEAD")
        with _opener.open(req, timeout=15) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl)
    except Exception:
        pass

    try:
        headers_with_range = dict(headers)
        headers_with_range["Range"] = "bytes=0-0"
        req = urllib.request.Request(url, headers=headers_with_range, method="GET")
        with _opener.open(req, timeout=15) as resp:
            cr = resp.headers.get("Content-Range") or ""
            # 示例: bytes 0-0/12345678
            m = re.search(r"/(\d+)$", cr)
            if m:
                return int(m.group(1))
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl)
    except Exception:
        pass

    try:
        # 部分 CDN 不支持 HEAD/Range，但普通 GET 头里会给出 Content-Length
        req = urllib.request.Request(url, headers=headers, method="GET")
        with _opener.open(req, timeout=15) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl)
            # 尝试读取极小分片后立即关闭，避免下载完整视频
            resp.read(1)
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl)
    except Exception:
        pass
    return 0


def extract_douyin_info(normalized_url: str) -> Dict:
    try:
        item = get_douyin_item_info(normalized_url)
    except Exception as e:
        raise Exception(f"抖音专用解析失败：{str(e)}。")

    video = item.get("video") or {}
    nowm_url = build_douyin_nowm_url(item)
    filesize = _probe_content_length(nowm_url)
    width = video.get("width", 0) or 0
    height = video.get("height", 0) or 0
    duration_ms = video.get("duration", 0) or 0
    duration_s = duration_ms / 1000 if duration_ms else 0
    author = (item.get("author") or {}).get("nickname", "N/A")
    title = item.get("desc") or "N/A"
    thumbnail = _get_first_url_from_addr(video.get("cover") or {})
    if thumbnail and thumbnail.startswith("http://"):
        thumbnail = thumbnail.replace("http://", "https://", 1)
    if thumbnail:
        thumbnail = (
            "/api/thumbnail?src="
            + urllib.parse.quote(thumbnail, safe="")
            + "&referer="
            + urllib.parse.quote(normalized_url, safe="")
        )

    return {
        "title": title,
        "duration": duration_s,
        "uploader": author,
        "view_count": item.get("statistics", {}).get("play_count", 0),
        "thumbnail": thumbnail,
        "formats": [
            {
                "format_id": "douyin_nowm",
                "format_note": "Douyin No Watermark",
                "ext": "mp4",
                "height": height,
                "width": width,
                "filesize": filesize,
                "fps": 0,
                "vcodec": "h264",
                "acodec": "aac",
                "is_video_only": False,
                "is_audio_only": False,
            }
        ],
    }


def parse_douyin_url(normalized_url: str) -> Dict:
    """
    仅做抖音解析：返回视频基础信息 + 无水印直链，不执行下载。
    """
    video_id = _extract_douyin_video_id(normalized_url)
    item = get_douyin_item_info(normalized_url)
    nowm_url = build_douyin_nowm_url(item)
    return {
        "video_id": video_id,
        "title": item.get("desc") or "N/A",
        "uploader": (item.get("author") or {}).get("nickname", "N/A"),
        "no_watermark_url": nowm_url,
        "raw_url": normalized_url,
    }


def download_douyin_video(normalized_url: str, temp_dir: str) -> Dict:
    item = get_douyin_item_info(normalized_url)
    direct_url = build_douyin_nowm_url(item)
    file_path = os.path.join(temp_dir, f"video_{os.urandom(8).hex()}.mp4")
    req = urllib.request.Request(
        direct_url,
        headers=_default_headers("https://www.douyin.com/"),
        method="GET",
    )
    with _opener.open(req, timeout=60) as resp, open(file_path, "wb") as fp:
        while True:
            chunk = resp.read(1024 * 128)
            if not chunk:
                break
            fp.write(chunk)

    return {
        "title": item.get("desc") or "Douyin Video",
        "file_path": file_path,
        "file_size": os.path.getsize(file_path),
        "ext": "mp4",
    }
