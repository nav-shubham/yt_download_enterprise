import asyncio
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import aiofiles
import httpx

from ..config import config_manager
from ..core.downloader import YtDlpDownloader
from ..exceptions import TaskNotFoundError
from ..logging_config import logger
from .metadata import MetadataService


class QueueManager:
    """Enterprise Asynchronous Queue and Task Manager."""
    
    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(QueueManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self.state_file = config_manager.state_file
        self.downloader = YtDlpDownloader()
        self.metadata_service = MetadataService()
        
        # Thread/Async Safe Task Store
        self._tasks_db: Dict[str, Dict[str, Any]] = {}
        self._db_lock = threading.Lock()
        
        # Event to wake up the worker loop
        self.activity_event = asyncio.Event()
        
        # Registry of active asyncio Tasks running downloads
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self._loop_task: Optional[asyncio.Task] = None
        self.client = httpx.AsyncClient(timeout=10.0)
        
        self._initialized = True

    def start_loop(self) -> None:
        """Starts the background worker queue loop."""
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._worker_loop())
            logger.info("Asynchronous background queue loop started.")

    async def shutdown(self) -> None:
        """Gracefully shutdown worker loop and active requests."""
        logger.info("Shutting down Queue Manager...")
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all active download tasks
        for task_id, task in list(self.active_tasks.items()):
            task.cancel()
            
        await self.client.aclose()
        logger.info("Queue Manager shutdown complete.")

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self._db_lock:
            if task_id not in self._tasks_db:
                raise TaskNotFoundError(f"Task with ID {task_id} not found.")
            return self._tasks_db[task_id].copy()

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        with self._db_lock:
            return [t.copy() for t in self._tasks_db.values()]

    def add_task(
        self,
        url: str,
        title: str,
        mode: str,
        resolution: str,
        is_playlist: bool,
        thumbnail: str,
    ) -> str:
        """Enqueue a new media download task."""
        import uuid
        task_id = str(uuid.uuid4())
        
        task = {
            "id": task_id,
            "url": url,
            "title": title,
            "mode": mode,
            "resolution": resolution,
            "is_playlist": is_playlist,
            "thumbnail": thumbnail,
            "status": "queued",
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "started_at": None,
            "completed_at": None,
            "percent": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed_str": "Queued",
            "eta_str": "--:--",
            "error": None,
        }
        
        with self._db_lock:
            self._tasks_db[task_id] = task
            
        logger.info(f"Task {task_id} added to queue: {title}")
        self._trigger_activity()
        return task_id

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> None:
        """Thread-safe update of task attributes."""
        with self._db_lock:
            if task_id in self._tasks_db:
                self._tasks_db[task_id].update(updates)
                # Debug logging for status changes
                if "status" in updates:
                    logger.debug(f"Task {task_id} status updated to: {updates['status']}")

    def _trigger_activity(self) -> None:
        """Wake up worker loop to check for work or changes."""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(self.activity_event.set)

    async def control_task(self, task_id: str, action: str) -> None:
        """Pause, resume, or delete a task from the queue."""
        logger.info(f"Task control action requested: {action} on {task_id}")
        
        with self._db_lock:
            if task_id not in self._tasks_db:
                raise TaskNotFoundError("Task not found.")
            task = self._tasks_db[task_id]

        if action == "pause":
            if task["status"] in ["downloading", "queued"]:
                self.update_task(task_id, {"status": "paused", "speed_str": "Paused", "eta_str": "--:--"})
                # Cancellation of download is handled via checking status in the progress hook
        
        elif action == "resume":
            if task["status"] in ["paused", "failed"]:
                self.update_task(task_id, {"status": "queued", "speed_str": "Queued", "error": None})
                self._trigger_activity()

        elif action == "delete":
            # Set state to deleted to force progress hook abort
            self.update_task(task_id, {"status": "deleted"})
            
            # Cancel active asyncio runner if exists
            if task_id in self.active_tasks:
                self.active_tasks[task_id].cancel()
                
            with self._db_lock:
                if task_id in self._tasks_db:
                    del self._tasks_db[task_id]
            logger.info(f"Task {task_id} deleted successfully.")
            self._trigger_activity()

    async def load_daily_state(self) -> Dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        default_state = {"date": today, "downloaded_today": 0}
        
        if not self.state_file.exists():
            return default_state

        try:
            async with aiofiles.open(self.state_file, "r", encoding="utf-8") as f:
                content = await f.read()
                data = json.loads(content)
                if data.get("date") != today:
                    return default_state
                return data
        except Exception as e:
            logger.warning(f"Failed to read daily state: {e}")
            return default_state

    async def increment_daily_state(self) -> None:
        """Safely increments the daily count of downloads."""
        state = await self.load_daily_state()
        state["downloaded_today"] += 1
        try:
            async with aiofiles.open(self.state_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(state, indent=2))
            logger.info(f"Incremented daily state. Total today: {state['downloaded_today']}")
        except Exception as e:
            logger.error(f"Failed saving daily state: {e}")

    async def notify_telegram(self, message: str) -> None:
        """Send asynchronous Telegram notification."""
        settings = config_manager.settings
        if not settings.telegram_enabled or not settings.telegram_bot_token or not settings.telegram_chat_id:
            return

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": settings.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }
        try:
            response = await self.client.post(url, json=payload, timeout=8.0)
            response.raise_for_status()
            logger.info("Telegram telemetry transmitted successfully.")
        except Exception as e:
            logger.warning(f"Telegram telemetry transmission failed: {e}")

    async def _worker_loop(self) -> None:
        """Main event-driven loop distributing tasks to worker threads."""
        while True:
            self.activity_event.clear()
            settings = config_manager.settings
            max_concurrent = settings.max_concurrent

            # Clean finished asyncio runner tasks
            finished_task_ids = [tid for tid, t in self.active_tasks.items() if t.done()]
            for tid in finished_task_ids:
                del self.active_tasks[tid]

            # Get queued tasks sorted by added time
            all_tasks = self.get_all_tasks()
            queued_tasks = [t for t in all_tasks if t["status"] == "queued"]
            queued_tasks.sort(key=lambda x: x["added_at"])

            available_slots = max_concurrent - len(self.active_tasks)
            if available_slots > 0 and queued_tasks:
                for i in range(min(available_slots, len(queued_tasks))):
                    task_to_run = queued_tasks[i]
                    task_id = task_to_run["id"]
                    
                    # Spawn download worker task
                    runner = asyncio.create_task(self._run_task_download(task_id))
                    self.active_tasks[task_id] = runner

            # Wait until something changes or a brief timeout
            try:
                await asyncio.wait_for(self.activity_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def _run_task_download(self, task_id: str) -> None:
        """Performs download pipeline, handles state transitions and telemetry."""
        try:
            with self._db_lock:
                if task_id not in self._tasks_db:
                    return
                task = self._tasks_db[task_id]
            
            # Check Daily Quota first
            daily_state = await self.load_daily_state()
            settings = config_manager.settings
            if daily_state["downloaded_today"] >= settings.videos_per_day:
                msg = f"⚠️ *Quota Limit Exceeded*\nDownload task '{task['title']}' paused because the daily limit of {settings.videos_per_day} is reached."
                logger.warning(msg)
                self.update_task(task_id, {
                    "status": "paused",
                    "speed_str": "Quota Exceeded",
                    "error": "Daily quota limit reached."
                })
                await self.notify_telegram(msg)
                return

            self.update_task(task_id, {
                "status": "downloading",
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            # Define progress hook function that runs in yt-dlp thread pool
            loop = asyncio.get_running_loop()
            
            def progress_hook(d: Dict[str, Any]) -> None:
                # 1. Check if user initiated abort (Pause/Delete)
                current_task = self.get_task(task_id)
                if current_task["status"] in ["paused", "deleted"]:
                    raise ValueError("ABORT_REQUESTED")

                if d["status"] == "downloading":
                    downloaded = d.get("downloaded_bytes", 0)
                    total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    percent = 0.0
                    if total > 0:
                        percent = (downloaded / total) * 100

                    speed = d.get("speed")
                    eta = d.get("eta")

                    # Dispatch database update thread-safely back to event loop
                    loop.call_soon_threadsafe(
                        self.update_task,
                        task_id,
                        {
                            "downloaded_bytes": downloaded,
                            "total_bytes": total,
                            "percent": round(percent, 2),
                            "speed_str": self._format_speed(speed),
                            "eta_str": self._format_eta(eta),
                        }
                    )
                elif d["status"] == "finished":
                    loop.call_soon_threadsafe(
                        self.update_task,
                        task_id,
                        {
                            "status": "merging",
                            "percent": 100.0,
                            "speed_str": "Merging segments",
                            "eta_str": "00:00",
                        }
                    )

            # Trigger Download Core
            await self.downloader.download(
                url=task["url"],
                mode=task["mode"],
                resolution=task["resolution"],
                is_playlist=task["is_playlist"],
                progress_hook=progress_hook
            )

            # Verification of final state
            final_task = self.get_task(task_id)
            if final_task["status"] == "paused":
                logger.info(f"Task {task_id} successfully paused.")
                return
            elif final_task["status"] == "deleted":
                logger.info(f"Task {task_id} successfully stopped and removed.")
                return

            # Complete!
            self.update_task(task_id, {
                "status": "completed",
                "percent": 100.0,
                "speed_str": "Completed",
                "eta_str": "00:00",
                "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            # Update daily states
            await self.increment_daily_state()

            # Async trigger metadata sync and logging
            asyncio.create_task(self._post_download_sync(task))
            
            # Send completion alert
            alert = f"✅ *Download Complete!*\n*Title:* {task['title']}\n*Mode:* {task['mode']}\n*Resolution:* {task['resolution']}p"
            await self.notify_telegram(alert)

        except Exception as e:
            err_str = str(e)
            if "ABORT_REQUESTED" in err_str:
                logger.info(f"Task {task_id} aborted during download hook.")
                # Ensure status is set to paused (if not already deleted)
                try:
                    task = self.get_task(task_id)
                    if task["status"] != "deleted":
                        self.update_task(task_id, {"status": "paused", "speed_str": "Paused"})
                except TaskNotFoundError:
                    pass
            else:
                logger.error(f"Execution failed for task {task_id}: {e}", exc_info=True)
                self.update_task(task_id, {
                    "status": "failed",
                    "speed_str": "Failed",
                    "eta_str": "--:--",
                    "error": err_str
                })
                # Log crash to error log file
                await self._log_error_to_file(task_id, err_str)
                await self.notify_telegram(f"❌ *Download Failed*\n*Task:* {task_id}\n*Error:* `{err_str}`")
        finally:
            # Wake up manager to trigger next slot
            self._trigger_activity()

    async def _post_download_sync(self, task: Dict[str, Any]) -> None:
        """Fetch metadata post-download and write to CSV."""
        try:
            # Sync metadata to CSV
            await self.metadata_service.run_metadata_sync()
        except Exception as ex:
            logger.warning(f"Post-download metadata sync error: {ex}")

    async def _log_error_to_file(self, task_id: str, error_msg: str) -> None:
        error_file = config_manager.ROOT_DIR / "errors.log"
        try:
            async with aiofiles.open(error_file, "a", encoding="utf-8") as f:
                await f.write(f"{datetime.now()} | {task_id} | {error_msg}\n")
        except Exception as e:
            logger.error(f"Failed to write to error log: {e}")

    def _format_speed(self, speed_bytes: Optional[float]) -> str:
        if speed_bytes is None:
            return "0 B/s"
        if speed_bytes >= 1024 * 1024:
            return f"{speed_bytes / (1024 * 1024):.2f} MB/s"
        elif speed_bytes >= 1024:
            return f"{speed_bytes / 1024:.2f} KB/s"
        return f"{speed_bytes:.0f} B/s"

    def _format_eta(self, eta_seconds: Optional[int]) -> str:
        if eta_seconds is None:
            return "Unknown"
        if eta_seconds >= 3600:
            h = eta_seconds // 3600
            m = (eta_seconds % 3600) // 60
            s = eta_seconds % 60
            return f"{h:02d}:{m:02d}:{s:02d}"
        else:
            m = eta_seconds // 60
            s = eta_seconds % 60
            return f"{m:02d}:{s:02d}"


# Singleton access
queue_manager = QueueManager()
