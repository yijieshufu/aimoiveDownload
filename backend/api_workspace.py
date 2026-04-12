from fastapi import APIRouter, HTTPException, Request

from .workspace_store import (
    get_tabs,
    save_tabs,
    get_mindmap,
    save_mindmap,
    get_summary_edit,
    save_summary_edit,
    delete_summary_edit,
)

router = APIRouter()


@router.get("/api/ui/tabs")
async def get_ui_tabs():
    try:
        return {"tabs": get_tabs()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/ui/tabs")
async def put_ui_tabs(request: Request):
    try:
        data = await request.json()
        tabs = data.get("tabs") or []
        return {"tabs": save_tabs(tabs)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/summarize/{task_id}/mindmap")
async def get_task_mindmap(task_id: str):
    try:
        return get_mindmap(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/api/summarize/{task_id}/mindmap")
async def put_task_mindmap(task_id: str, request: Request):
    try:
        data = await request.json()
        return save_mindmap(task_id, data.get("mindmap") or {})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/summarize/{task_id}/summary-edit")
async def get_task_summary_edit(task_id: str):
    try:
        row = get_summary_edit(task_id)
        if not row:
            return {"task_id": task_id, "sections": None, "updated_at": None}
        return {"task_id": task_id, "sections": row["sections"], "updated_at": row["updated_at"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/api/summarize/{task_id}/summary-edit")
async def put_task_summary_edit(task_id: str, request: Request):
    try:
        data = await request.json()
        sections = data.get("sections")
        if not isinstance(sections, dict):
            raise Exception("sections 必须为对象")
        return save_summary_edit(task_id, sections)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/summarize/{task_id}/summary-edit")
async def delete_task_summary_edit(task_id: str):
    try:
        delete_summary_edit(task_id)
        return {"task_id": task_id, "ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
