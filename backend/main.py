import os

from .env_bootstrap import load_dotenv_files

load_dotenv_files()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .auth_routes import router as auth_router
from .billing_routes import router as billing_router
from .api_video import router as video_router
from .api_summarize import router as summarize_router
from .api_workspace import router as workspace_router

app = FastAPI(
    title="Video Downloader API",
    description="A powerful API for downloading videos from various platforms",
    version="1.0.0",
)
init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dist_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
app.mount("/frontend", StaticFiles(directory=frontend_dist_dir, html=True), name="frontend")

app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(video_router)
app.include_router(summarize_router)
app.include_router(workspace_router)


@app.get("/")
async def root():
    return {"message": "Video Downloader API is running"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
