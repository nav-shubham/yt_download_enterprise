import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import yt_dlp

from ..config import config_manager
from ..exceptions import DownloaderConfigurationError, YtDownloadError
from ..logging_config import logger


class YtDlpDownloader:
    """Core download service wrapping yt-dlp."""

    def __init__(self) -> None:
        self.cookie_file = config_manager.cookie_file
        self.archive_file = config_manager.archive_file

    def _get_base_opts(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "js_runtimes": {"node": {}},
        }
        if self.cookie_file.exists():
            opts["cookiefile"] = str(self.cookie_file)
        return opts

    async def fetch_info(self, url: str) -> Dict[str, Any]:
        """Extract metadata from URL without downloading."""
        logger.info(f"Extracting metadata for URL: {url}")
        loop = asyncio.get_running_loop()
        
        opts = self._get_base_opts()
        opts.update({
            "skip_download": True,
            "extract_flat": "in_playlist",
        })

        try:
            # Run blocking extraction in a thread pool
            info = await loop.run_in_executor(
                None, 
                lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False)
            )
        except Exception as e:
            logger.error(f"Failed to fetch metadata: {e}", exc_info=True)
            raise YtDownloadError(f"Failed to extract metadata: {str(e)}")

        if not info:
            raise YtDownloadError("No metadata returned by extractor.")

        is_playlist = "entries" in info
        title = info.get("title") or "Unknown Title"
        thumbnail = info.get("thumbnail") or ""
        duration_sec = info.get("duration", 0)

        # Parse duration
        if is_playlist:
            entries = info.get("entries") or []
            duration_str = f"{len(entries)} videos"
            if entries and not thumbnail:
                thumbnail = entries[0].get("thumbnail") or ""
        else:
            duration_str = self._format_duration(duration_sec) if duration_sec else "Unknown"

        # Parse resolutions
        formats = info.get("formats", [])
        resolutions = set()
        for f in formats:
            height = f.get("height")
            if height and height in [144, 240, 360, 480, 720, 1080, 1440, 2160]:
                resolutions.add(str(height))

        res_list = sorted(list(resolutions), key=lambda x: int(x), reverse=True)
        if not res_list:
            res_list = ["1080", "720", "480", "360"]

        return {
            "title": title,
            "thumbnail": thumbnail,
            "duration": duration_str,
            "resolutions": res_list,
            "is_playlist": is_playlist,
            "uploader": info.get("uploader") or "Unknown Creator",
        }

    async def download(
        self,
        url: str,
        mode: str,
        resolution: str,
        is_playlist: bool,
        progress_hook: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Download video/audio from URL."""
        logger.info(f"Initiating download pipeline. Mode: {mode}, Resolution: {resolution}, URL: {url}")
        settings = config_manager.settings
        loop = asyncio.get_running_loop()

        # Build Format
        if mode == "audio":
            format_option = "bestaudio[ext=m4a]/bestaudio/best"
        else:
            format_option = f"bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

        out_template = str(Path(settings.download_dir) / "%(playlist_title)s/%(title)s.%(ext)s")
        if is_playlist:
            out_template = str(Path(settings.download_dir) / "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s")

        ydl_opts = self._get_base_opts()
        ydl_opts.update({
            "format": format_option,
            "outtmpl": out_template,
            "download_archive": str(self.archive_file),
            "ignoreerrors": True,
            "concurrent_fragment_downloads": settings.concurrent_fragments,
            "retries": 10,
            "fragment_retries": 10,
            "socket_timeout": 30,
            "progress_hooks": [progress_hook],
        })

        try:
            # Run blocking download in a thread pool
            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(ydl_opts).download([url])
            )
        except Exception as e:
            logger.error(f"Download pipeline encountered error: {e}", exc_info=True)
            raise YtDownloadError(f"Download failed: {str(e)}")

    def _format_duration(self, eta_seconds: int) -> str:
        if eta_seconds >= 3600:
            h = eta_seconds // 3600
            m = (eta_seconds % 3600) // 60
            s = eta_seconds % 60
            return f"{h:02d}:{m:02d}:{s:02d}"
        else:
            m = eta_seconds // 60
            s = eta_seconds % 60
            return f"{m:02d}:{s:02d}"
