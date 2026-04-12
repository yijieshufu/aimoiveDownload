import json
import os
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .account_store import get_subscription
from .auth_routes import get_current_user_id
from .summarizer import (
    create_summary_task_with_options,
    get_summary_task,
    ask_summary_question,
    translate_summary,
    get_task_subtitle_segments,
    build_task_subtitle_file,
    stream_summary_task,
    chat_with_summary,
)
from .usage_limits import assert_can_summarize, check_burst, record_summarize
from .workspace_store import (
    append_chat_message,
    get_chat_messages,
)

router = APIRouter()


@router.post("/api/summarize")
async def start_summarize(request: Request):
    check_burst(request, "summarize")
    try:
        data = await request.json()
        url = data.get("url")
        stream = bool(data.get("stream") or False)
        if not url:
            raise HTTPException(status_code=400, detail="缺少URL参数")
        uid = get_current_user_id(request)
        sub = get_subscription(uid or "")
        assert_can_summarize(request, uid, sub)
        task_id = create_summary_task_with_options(url, start_thread=(not stream))
        record_summarize(request, uid, sub)
        return {"task_id": task_id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/summarize/{task_id}")
async def summarize_status(task_id: str):
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


@router.get("/api/summarize/{task_id}/stream")
async def summarize_stream(task_id: str):
    def gen():
        for item in stream_summary_task(task_id):
            event = item.get("event") or "message"
            data = json.dumps(item.get("data") or {}, ensure_ascii=False)
            yield f"event: {event}\n"
            yield f"data: {data}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/api/summarize/{task_id}/qa")
async def summarize_qa(task_id: str, request: Request):
    try:
        data = await request.json()
        question = data.get("question")
        result = ask_summary_question(task_id, question)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/summarize/{task_id}/chat")
async def summarize_chat(task_id: str, request: Request):
    try:
        data = await request.json()
        message = str(data.get("message") or "").strip()
        if not message:
            raise Exception("message 不能为空")
        append_chat_message(task_id, "user", message)
        history = get_chat_messages(task_id, limit=30)
        resp = chat_with_summary(task_id, history)
        append_chat_message(task_id, "assistant", resp.get("answer") or "")
        return {
            "task_id": task_id,
            "messages": get_chat_messages(task_id, limit=60),
            "answer": resp.get("answer") or "",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/summarize/{task_id}/translate")
async def summarize_translate(task_id: str, request: Request):
    try:
        data = await request.json()
        target_language = data.get("target_language", "zh")
        return translate_summary(task_id, target_language)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/summarize/{task_id}/subtitles")
async def summarize_subtitles(task_id: str):
    try:
        return get_task_subtitle_segments(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/summarize/{task_id}/subtitles/download")
async def summarize_subtitles_download(task_id: str, format: str = "srt"):
    try:
        out_path = build_task_subtitle_file(task_id, format)

        media_type = "text/plain"
        if format == "srt":
            media_type = "application/x-subrip"
        if format == "vtt":
            media_type = "text/vtt"
        return FileResponse(
            path=os.path.realpath(out_path),
            filename=os.path.basename(out_path),
            media_type=media_type,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
