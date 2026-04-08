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
from .summarizer import create_summary_task, get_summary_task, ask_summary_question, translate_summary
from .workspace_store import get_tabs, save_tabs, get_mindmap, save_mindmap, init_workspace_store

app = FastAPI(
    title="Video Downloader API",
    description="A powerful API for downloading videos from various platforms",
    version="1.0.0"
)
init_workspace_store()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录（Vue 构建产物）
frontend_dist_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
app.mount("/frontend", StaticFiles(directory=frontend_dist_dir, html=True), name="frontend")

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


@app.post("/api/summarize")
async def start_summarize(request: Request):
    """
    创建异步视频总结任务。
    """
    try:
        data = await request.json()
        url = data.get("url")
        if not url:
            raise Exception("缺少URL参数")
        task_id = create_summary_task(url)
        return {"task_id": task_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/summarize/{task_id}")
async def summarize_status(task_id: str):
    """
    查询异步总结任务状态。
    """
    try:
        task = get_summary_task(task_id)
        payload = {
            "task_id": task["task_id"],
            "status": task["status"],
            "stage": task.get("stage"),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
        }
        result = task.get("result")
        if result:
            payload["result"] = dict(result)
            md_path = result.get("markdown_file_path")
            if md_path:
                payload["result"]["markdown_download_url"] = (
                    "/api/download/file?file_path=" + urllib.parse.quote(md_path, safe="")
                )
        return payload
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/summarize/{task_id}/qa")
async def summarize_qa(task_id: str, request: Request):
    """
    基于总结结果进行 AI 问答。
    """
    try:
        data = await request.json()
        question = data.get("question")
        result = ask_summary_question(task_id, question)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/summarize/{task_id}/translate")
async def summarize_translate(task_id: str, request: Request):
    """
    将已完成总结翻译为目标语言（默认中文）。
    """
    try:
        data = await request.json()
        target_language = data.get("target_language", "zh")
        return translate_summary(task_id, target_language)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ui/tabs")
async def get_ui_tabs():
    try:
        return {"tabs": get_tabs()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/ui/tabs")
async def put_ui_tabs(request: Request):
    try:
        data = await request.json()
        tabs = data.get("tabs") or []
        return {"tabs": save_tabs(tabs)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/summarize/{task_id}/mindmap")
async def get_task_mindmap(task_id: str):
    try:
        return get_mindmap(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/summarize/{task_id}/mindmap")
async def put_task_mindmap(task_id: str, request: Request):
    try:
        data = await request.json()
        return save_mindmap(task_id, data.get("mindmap") or {})
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
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少 file_path 参数")

        requested_path = os.path.realpath(file_path)
        temp_root = os.path.realpath(temp_dir)
        if not requested_path.startswith(temp_root + os.sep):
            raise HTTPException(status_code=403, detail="不允许访问 temp 目录之外的文件")

        if not os.path.exists(requested_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        from fastapi.responses import FileResponse
        return FileResponse(
            path=requested_path,
            filename=os.path.basename(requested_path),
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