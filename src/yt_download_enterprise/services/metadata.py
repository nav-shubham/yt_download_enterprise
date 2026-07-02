import asyncio
import csv
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set
import aiofiles
import yt_dlp

from ..config import config_manager
from ..exceptions import MetadataExportError
from ..logging_config import logger


class MetadataService:
    """Service to extract and log YouTube video metadata to a CSV datastore."""

    def __init__(self) -> None:
        self.csv_file = config_manager.csv_file
        self.archive_file = config_manager.archive_file
        self.cookie_file = config_manager.cookie_file
        self._write_lock = asyncio.Lock()

    async def extract_ids_from_archive(self) -> List[str]:
        """Extract YouTube 11-char video IDs from downloaded.txt archive."""
        if not self.archive_file.exists():
            return []

        logger.debug(f"Reading video IDs from archive: {self.archive_file}")
        video_ids = []
        id_pattern = re.compile(r"youtube\s+([A-Za-z0-9_-]{11})")

        try:
            async with aiofiles.open(self.archive_file, "r", encoding="utf-8") as f:
                async for line in f:
                    match = id_pattern.search(line)
                    if match:
                        video_ids.append(match.group(1))
            return list(set(video_ids))
        except Exception as e:
            logger.error(f"Failed to parse download archive: {e}")
            raise MetadataExportError(f"Error parsing download archive: {str(e)}")

    async def load_existing_ids(self) -> Set[str]:
        """Load already processed video IDs from CSV registry."""
        if not self.csv_file.exists():
            logger.debug("No existing CSV database found; returning empty registry.")
            return set()

        existing_ids = set()
        loop = asyncio.get_running_loop()

        # Run blocking CSV reading in thread pool
        def _read():
            with open(self.csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or "video_id" not in reader.fieldnames:
                    return set()
                return {row["video_id"].strip() for row in reader if row.get("video_id")}

        try:
            existing_ids = await loop.run_in_executor(None, _read)
            logger.info(f"Loaded {len(existing_ids)} video IDs from CSV.")
            return existing_ids
        except Exception as e:
            logger.error(f"Error reading CSV metadata: {e}")
            raise MetadataExportError(f"Failed to load existing metadata records: {str(e)}")

    async def append_metadata_row(self, data: Dict[str, Any]) -> None:
        """Append a single metadata row to CSV file (concurrency safe)."""
        async with self._write_lock:
            loop = asyncio.get_running_loop()
            file_exists = self.csv_file.exists()

            def _write():
                # Open in append mode
                with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=list(data.keys()))
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(data)

            try:
                await loop.run_in_executor(None, _write)
                logger.debug(f"Logged metadata row for video ID: {data.get('video_id')}")
            except Exception as e:
                logger.error(f"CSV append failure: {e}")
                raise MetadataExportError(f"Failed to log metadata row: {str(e)}")

    async def fetch_video_metadata(self, video_id: str) -> Dict[str, Any]:
        """Fetch video info via yt-dlp without downloading."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        loop = asyncio.get_running_loop()

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "js_runtimes": {"node": {}},
            "extractor_args": {"youtube": {"player_client": ["web"]}},
        }
        if self.cookie_file.exists():
            ydl_opts["cookiefile"] = str(self.cookie_file)

        def _fetch():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            info = await loop.run_in_executor(None, _fetch)
            if not info:
                raise MetadataExportError("Received empty payload from extractor.")

            return {
                "video_id": video_id,
                "title": info.get("title") or "Unknown Title",
                "channel": info.get("uploader") or "Unknown Channel",
                "views": info.get("view_count") or 0,
                "duration": info.get("duration") or 0,
                "upload_date": info.get("upload_date") or "",
                "url": url,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            logger.error(f"Failed fetching metadata for video {video_id}: {e}")
            raise MetadataExportError(f"Metadata extraction failed: {str(e)}")

    async def run_metadata_sync(self) -> int:
        """Sync new video IDs from archive to CSV registry."""
        logger.info("Starting background metadata sync...")
        try:
            archive_ids = await self.extract_ids_from_archive()
            existing_ids = await self.load_existing_ids()
            
            new_ids = [vid for vid in archive_ids if vid not in existing_ids]
            if not new_ids:
                logger.info("Metadata registry is already fully synchronized.")
                return 0

            logger.info(f"Syncing metadata for {len(new_ids)} new videos...")
            synced_count = 0

            for vid in new_ids:
                # Add delay or retries to avoid rate limits
                for attempt in range(3):
                    try:
                        metadata = await self.fetch_video_metadata(vid)
                        await self.append_metadata_row(metadata)
                        synced_count += 1
                        break
                    except Exception as e:
                        if attempt == 2:
                            logger.error(f"Failed to sync video {vid} after 3 attempts: {e}")
                        else:
                            await asyncio.sleep(2)
            
            logger.info(f"Metadata sync complete. Added {synced_count} videos.")
            return synced_count
        except Exception as e:
            logger.error(f"Metadata sync aborted: {e}")
            raise
