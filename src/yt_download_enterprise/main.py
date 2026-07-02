import asyncio
import os
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from .api.routes import router
from .config import config_manager
from .logging_config import logger
from .services.queue_manager import queue_manager

# Setup App directories relative to config
APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

# Ensure templates and static directories exist
TEMPLATES_DIR.mkdir(exist_ok=True, parents=True)
STATIC_DIR.mkdir(exist_ok=True, parents=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Asynchronous lifespan manager for FastAPI app lifecycle."""
    # Startup Sequence
    logger.info("Initializing enterprise application resources...")
    queue_manager.start_loop()
    logger.info("Startup sequence complete. Download engine online.")
    yield
    # Shutdown Sequence
    logger.info("Shutting down application resources...")
    await queue_manager.shutdown()
    logger.info("Shutdown sequence complete. Off.")


app = FastAPI(
    title="YouTube Download Automation Suite",
    description="Enterprise-level high-performance YouTube downloader with concurrent queuing, VTT cleaning, and Telegram telemetry.",
    version="1.0.0",
    lifespan=lifespan
)

# Mount Static assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include Core Router
app.include_router(router)

@app.get("/")
async def serve_dashboard():
    """Serves the front-end dashboard UI page."""
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        logger.error(f"UI file not found: {index_file}")
        return {"error": "Dashboard index.html not found. Place it in the templates directory."}
    return FileResponse(index_file)


def run():
    """Application startup launcher (Uvicorn)."""
    # Open default browser after a brief delay to ensure ASGI socket binds
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8000")

    logger.info("Engaging browser auto-launch thread...")
    threading.Thread(target=open_browser, daemon=True).start()

    logger.info("Launching Uvicorn ASGI production server at http://127.0.0.1:8000")
    uvicorn.run(
        "yt_download_enterprise.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,  # Set False for production stability
        log_level="info"
    )


if __name__ == "__main__":
    run()
