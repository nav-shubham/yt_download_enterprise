import json
from pathlib import Path
import threading
from typing import Any, Dict
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base Directories
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent.parent

class AppSettings(BaseSettings):
    download_dir: str = Field(default=str(ROOT_DIR / "downloads"), description="Output directory for downloads")
    max_concurrent: int = Field(default=2, ge=1, le=10, description="Max concurrent video downloads")
    default_resolution: str = Field(default="1080", description="Default video resolution limit")
    default_mode: str = Field(default="video", description="Default format mode (video/audio)")
    telegram_enabled: bool = Field(default=False, description="Enable Telegram remote notifications")
    telegram_bot_token: str = Field(default="", description="Telegram Bot API Token")
    telegram_chat_id: str = Field(default="", description="Telegram chat or group ID")
    concurrent_fragments: int = Field(default=5, ge=1, le=16, description="Aria-Segment/fragment connection limit")
    videos_per_day: int = Field(default=40, ge=1, description="Daily limit allocation for downloads")

    # Load from .env file optionally
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


class ConfigManager:
    """Thread-safe manager for app configuration lifecycle."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = threading.Lock()
        self.settings_file = ROOT_DIR / "settings.json"
        self.archive_file = ROOT_DIR / "downloaded.txt"
        self.state_file = ROOT_DIR / "daily_state.json"
        self.cookie_file = ROOT_DIR / "cookies.txt"
        self.csv_file = ROOT_DIR / "youtube_no_api.csv"
        self.log_dir = ROOT_DIR / "logs"
        
        # Ensure directories exist
        self.log_dir.mkdir(exist_ok=True, parents=True)
        
        self._settings = self._load_initial_settings()
        self._initialized = True

    def _load_initial_settings(self) -> AppSettings:
        # 1. Start with env variables / Pydantic defaults
        settings = AppSettings()
        
        # 2. If settings.json exists, merge and validate
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Overwrite defaults with saved config
                merged_data = settings.model_dump()
                merged_data.update({k: v for k, v in data.items() if v is not None})
                settings = AppSettings(**merged_data)
            except Exception as e:
                print(f"[!] Error loading settings.json, reverting to defaults: {e}")
                self.save_settings(settings)
        else:
            self.save_settings(settings)
            
        # Ensure download directory is created
        Path(settings.download_dir).mkdir(exist_ok=True, parents=True)
        return settings

    @property
    def settings(self) -> AppSettings:
        with self._lock:
            return self._settings

    def update_settings(self, new_data: Dict[str, Any]) -> AppSettings:
        """Atomically validate and update app settings."""
        with self._lock:
            current_data = self._settings.model_dump()
            current_data.update(new_data)
            
            # Validate via Pydantic
            validated = AppSettings(**current_data)
            self._settings = validated
            
            # Persist to disk
            self.save_settings(validated)
            
            # Create download dir if changed
            Path(validated.download_dir).mkdir(exist_ok=True, parents=True)
            return validated

    def save_settings(self, settings: AppSettings) -> None:
        """Write settings to file safely."""
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(settings.model_dump(), f, indent=2)
        except Exception as e:
            print(f"[!] Failed to save settings.json: {e}")


# Singleton access
config_manager = ConfigManager()


def get_settings() -> AppSettings:
    return config_manager.settings
