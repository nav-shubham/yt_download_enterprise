import csv
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl

from ..config import config_manager, get_settings
from ..core.downloader import YtDlpDownloader
from ..exceptions import TaskNotFoundError, YtDownloadError
from ..logging_config import logger
from ..services.queue_manager import queue_manager

router = APIRouter()
downloader = YtDlpDownloader()

# ==========================================
# PYDANTIC SCHEMAS FOR JSON VALIDATION
# ==========================================

class SettingsUpdateSchema(BaseModel):
    download_dir: Optional[str] = None
    max_concurrent: Optional[int] = None
    default_resolution: Optional[str] = None
    default_mode: Optional[str] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    concurrent_fragments: Optional[int] = None
    videos_per_day: Optional[int] = None


class FetchInfoSchema(BaseModel):
    url: str


class AddToQueueSchema(BaseModel):
    url: str
    title: str
    mode: str
    resolution: str
    is_playlist: bool
    thumbnail: str


class QueueControlSchema(BaseModel):
    task_id: str
    action: str  # "pause", "resume", "delete"


# ==========================================
# ENDPOINTS
# ==========================================

@router.get("/api/settings")
async def get_settings_endpoint():
    """Retrieve current system settings."""
    settings = get_settings()
    return settings.model_dump()


@router.post("/api/settings")
async def update_settings_endpoint(payload: SettingsUpdateSchema):
    """Atomically update settings fields."""
    try:
        # Filter out None fields
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        updated_settings = config_manager.update_settings(updates)
        return {"status": "success", "settings": updated_settings.model_dump()}
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid configuration parameters: {str(e)}")


@router.post("/api/fetch-info")
async def fetch_info_endpoint(payload: FetchInfoSchema):
    """Analyze a URL and extract metadata (resolutions, formats, streams)."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty.")

    try:
        info = await downloader.fetch_info(url)
        return {"status": "success", **info}
    except YtDownloadError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected metadata parsing error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse remote media stream info.")


@router.post("/api/queue/add")
async def add_to_queue_endpoint(payload: AddToQueueSchema):
    """Enqueue a new media item to the download manager."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty.")

    try:
        task_id = queue_manager.add_task(
            url=url,
            title=payload.title,
            mode=payload.mode,
            resolution=payload.resolution,
            is_playlist=payload.is_playlist,
            thumbnail=payload.thumbnail,
        )
        return {"status": "success", "task_id": task_id}
    except Exception as e:
        logger.error(f"Enqueue task failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error enqueuing download task.")


@router.get("/api/queue")
async def get_queue_endpoint():
    """Get active download queue items, sorted by state priority."""
    tasks = queue_manager.get_all_tasks()
    
    # Priority sorting mapping
    status_order = {
        "downloading": 0,
        "merging": 1,
        "queued": 2,
        "paused": 3,
        "completed": 4,
        "failed": 5,
        "deleted": 6,
    }
    tasks.sort(key=lambda x: (status_order.get(x["status"], 9), x["added_at"]))
    return tasks


@router.post("/api/queue/control")
async def queue_control_endpoint(payload: QueueControlSchema):
    """Pause, resume, or delete download tasks."""
    if payload.action not in ["pause", "resume", "delete"]:
        raise HTTPException(status_code=400, detail="Invalid action request.")

    try:
        await queue_manager.control_task(payload.task_id, payload.action)
        return {"status": "success"}
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Task control operation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute control action.")


@router.get("/api/history")
async def get_history_endpoint():
    """Retrieve history of completed downloads from the CSV database registry."""
    csv_file = config_manager.csv_file
    if not csv_file.exists():
        return []

    try:
        history = []
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                history.append(row)
        
        # Newest first
        history.reverse()
        # Cap at 100 entries for client-side display performance
        return history[:100]
    except Exception as e:
        logger.error(f"Failed to read database history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve download history records.")


@router.get("/api/stats")
async def get_stats_endpoint():
    """Get dynamic statistics for the dashboard UI."""
    try:
        today_state = await queue_manager.load_daily_state()
        settings = get_settings()

        total_downloads = 0
        csv_file = config_manager.csv_file
        if csv_file.exists():
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    # Subtract 1 for CSV header row
                    total_downloads = max(0, sum(1 for _ in f) - 1)
            except Exception:
                pass

        return {
            "downloaded_today": today_state["downloaded_today"],
            "daily_quota": settings.videos_per_day,
            "total_downloads": total_downloads,
        }
    except Exception as e:
        logger.error(f"Stats generation failure: {e}")
        raise HTTPException(status_code=500, detail="Failed to compile dashboard metrics.")
