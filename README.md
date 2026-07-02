# YouTube Download Automation Suite — Enterprise Edition

An enterprise-grade, high-performance local YouTube downloader and playlist media extractor. This application has been upgraded from a basic script to a clean, asynchronous architecture built with a **FastAPI** web core, type-safe **Pydantic** settings validation, a robust **asyncio-based task queue** with worker slots and cancellation support, structured **rotating file logging**, and complete package management via **uv**.

---

## Key Features

1. **Clean Architecture**: Decoupled package structure containing core downloading wrappers, business logic services (Subtitles, Metadata syncing), REST controllers, and frontend templates/static file assets.
2. **FastAPI ASGI Backend**: Modern, high-concurrency async REST API replacing the legacy synchronous Flask server, featuring automatic schema validation, fast route resolution, and self-documenting JSON schemas.
3. **Asynchronous Task Queue Manager**: Thread-safe worker queue managing queued download tasks with concurrency limits, pause/resume hooks, graceful cancellation, and automatic resource cleanup.
4. **Reliable Subtitle Pipeline**: Automatic English/automatic caption downloads and cleaning wrapper that cleans transcripts (deduplicating repeats, removing speaker tags, and filtering out timestamps) into clean reading text formats (`VTT` → `TXT`).
5. **Concurrency-Safe Registry**: Lock-secured CSV logger tracking all downloaded videos preventing corruptions and deduplicating archive entries.
6. **Telegram Telemetry Notifications**: Dynamic non-blocking alerting alerts about completed downloads, system warnings, or failures.
7. **Pydantic Validation**: Centralized environment configuration via `pydantic-settings` reading from environment variables (`.env`) or saved profiles (`settings.json`).
8. **Modern Packaging with `uv`**: Uses the extremely fast package manager `uv` for workspace project definition and lockfiles instead of traditional `pip` and raw requirements.

---

## Project Structure

```text
yt_download_enterprise/
├── .venv/                         # Managed Python virtual environment
├── logs/                          # Self-cleaning rotated file logs
│   └── app.log                    # Diagnostic output logs
├── src/
│   └── yt_download_enterprise/
│       ├── __init__.py
│       ├── config.py              # Pydantic settings and configuration lifecycle
│       ├── exceptions.py          # Centralized domain exception hierarchy
│       ├── logging_config.py      # Console and RotatingFileLogger configuration
│       ├── main.py                # ASGI application setup & uvicorn entrypoint
│       ├── core/
│       │   ├── __init__.py
│       │   └── downloader.py      # yt-dlp core wrapper executing in thread pools
│       ├── services/
│       │   ├── __init__.py
│       │   ├── queue_manager.py   # Async task queue worker and notifications
│       │   ├── subtitles.py       # Subtitle scraper and VTT cleaner
│       │   └── metadata.py        # Safe CSV metadata tracking service
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes.py          # FastAPI REST endpoints
│       ├── templates/
│       │   └── index.html         # Glassmorphic IDM-styled front-end UI
│       └── static/
│           ├── css/
│           │   └── style.css      # Premium stylesheet
│           └── js/
│               └── app.js         # AJAX dashboard controller
├── tests/
│   └── test_subtitles.py          # Unit tests verifying cleaning logic
├── .env                           # Local environment config variables
├── pyproject.toml                 # uv package definition file
└── README.md                      # Documentation
```

---

## Installation & Setup

Ensure you have [uv](https://github.com/astral-sh/uv) installed.

### 1. Install Dependencies
Initialize and sync the project environment:
```bash
uv sync
```
This command automatically reads the `pyproject.toml` definition, locks the environment, and configures the `.venv`.

### 2. Configure Environment variables
Create a `.env` file in the root folder to set up Telegram notifications:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## Running the Application

To run the application server:
```bash
uv run main.py
```
This launches Uvicorn on `http://127.0.0.1:8000` and automatically opens the dashboard interface in your default web browser.

---

## Running Unit Tests

We use `pytest` combined with `pytest-asyncio` for asynchronous service testing. To run the test suite:
```bash
uv run pytest
```
This tests the VTT to TXT subtitle parsing service, making sure HTML tag scrubbing, speaker tag removals, and duplicate line deduplications run accurately.

---

## Architecture Flow

The download pipeline works as follows:
1. **Fetch**: User inputs a URL and clicks "Analyze". FastAPI triggers `YtDlpDownloader.fetch_info()` which extracts metadata asynchronously.
2. **Enqueue**: User configures quality and adds to queue. A task is registered in `QueueManager` with a `"queued"` state.
3. **Process**: The background worker picks the task, checks the daily state quota, and launches a worker thread running `yt-dlp`.
4. **Telemetry**: While downloading, progress hooks push segments status updates thread-safely to the FastAPI event loop, exposing progress percentages and speed metrics.
5. **Registry**: Upon download completion, subtitle cleaning and metadata logging to the CSV registry are performed concurrently.

---
*Developed with best practices in Clean Code, Async IO, and Modern Python packaging.*
