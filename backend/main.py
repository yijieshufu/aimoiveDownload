from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import json
import os
import urllib.request
import urllib.parse

from .downloader import extract_video_info, download_video, normalize_input_to_url
from .douyin_parser import is_douyin_url, parse_douyin_url

app = FastAPI(
    title="Video Downloader API",
    description="A powerful API for downloading videos from various platforms",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")

# cookies.txt 保存位置（用于抖音等需要 cookie 的站点）
temp_dir = os.path.join(os.getcwd(), "temp")
os.makedirs(temp_dir, exist_ok=True)
cookie_file_path = os.path.join(temp_dir, "cookies.txt")

@app.get("/")
async def root():
    return {"message": "Video Downloader API is running"}

@app.post("/api/extract")
async def extract_info(request: Request):
    """提取视频信息"""
    try:
        data = await request.json()
        url = data.get('url')
        if not url:
            raise Exception("缺少URL参数")
        info = extract_video_info(url)
        return info
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/douyin/parse")
async def parse_douyin(request: Request):
    """
    仅解析抖音视频，返回 video_id 和无水印播放地址。
    """
    try:
        data = await request.json()
        url = data.get("url")
        normalized_url = normalize_input_to_url(url)
        if not normalized_url:
            raise Exception("缺少URL参数")
        if not is_douyin_url(normalized_url):
            raise Exception("仅支持抖音链接（douyin.com / iesdouyin.com）")
        return parse_douyin_url(normalized_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/download")
async def download(url: str, format_id: str):
    """下载视频"""
    try:
        if not url or not format_id:
            raise Exception("缺少URL或format_id参数")
        result = download_video(url, format_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/download/file")
async def download_file(file_path: str):
    """下载文件"""
    try:
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        from fastapi.responses import FileResponse
        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type='application/octet-stream'
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/cookies/status")
async def cookies_status():
    return {"has_cookies": os.path.exists(cookie_file_path), "path": cookie_file_path}


@app.post("/api/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)):
    """
    上传 Netscape 格式 cookies.txt，用于抖音等站点解析。
    """
    try:
        if not file:
            raise HTTPException(status_code=400, detail="缺少文件")
        content = await file.read()
        if not content or len(content) < 20:
            raise HTTPException(status_code=400, detail="cookies 文件内容为空或过短")

        # 简单校验：Netscape cookies 常见包含这些字段
        text_head = content[:2000].decode("utf-8", errors="ignore")
        if "Netscape" not in text_head and "\t" not in text_head:
            raise HTTPException(status_code=400, detail="cookies 文件格式可能不正确（需要 Netscape cookies.txt）")

        with open(cookie_file_path, "wb") as f:
            f.write(content)

        return {"ok": True, "path": cookie_file_path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"上传 cookies 失败: {str(e)}")


@app.get("/api/thumbnail")
async def proxy_thumbnail(src: str, referer: str | None = None):
    """
    代理图片请求，解决部分站点（如 bilibili）封面防盗链导致浏览器直接加载 403 的问题。
    """
    if not src:
        raise HTTPException(status_code=400, detail="缺少src参数")

    try:
        # 基本校验：只允许 http/https
        parsed = urllib.parse.urlparse(src)
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(status_code=400, detail="不支持的src协议")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        else:
            # bilibili 常见需要 Referer
            headers["Referer"] = "https://www.bilibili.com/"

        req = urllib.request.Request(src, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read()
            content_type = r.headers.get("Content-Type") or "image/jpeg"
            return Response(
                content=content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=3600",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"封面代理失败: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)