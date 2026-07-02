import asyncio
import os
import re
from pathlib import Path
from typing import Optional
import aiofiles
import yt_dlp

from ..config import config_manager
from ..exceptions import YtDownloadError
from ..logging_config import logger


class SubtitleService:
    """Service to download and process YouTube subtitles (VTT to TXT)."""

    def __init__(self) -> None:
        self.cookie_file = config_manager.cookie_file

    async def download_subtitles(self, url: str) -> None:
        """Download automatic/written English subtitles for URL without video."""
        logger.info(f"Downloading subtitles for URL: {url}")
        settings = config_manager.settings
        loop = asyncio.get_running_loop()

        ydl_opts = {
            "skip_download": True,  # Do not download video/audio
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "outtmpl": str(Path(settings.download_dir) / "%(playlist_title)s/%(title)s.%(ext)s"),
            "ignoreerrors": True,
            "quiet": True,
            "no_warnings": True,
        }
        if self.cookie_file.exists():
            ydl_opts["cookiefile"] = str(self.cookie_file)

        try:
            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(ydl_opts).download([url])
            )
        except Exception as e:
            logger.error(f"Subtitle download failed: {e}", exc_info=True)
            raise YtDownloadError(f"Failed to download subtitles: {str(e)}")

    async def clean_vtt_to_txt(self, vtt_path: Path) -> Path:
        """Clean WebVTT file metadata and timestamps into readable text format."""
        logger.info(f"Converting VTT to TXT: {vtt_path}")
        txt_path = vtt_path.with_suffix(".txt")

        if not vtt_path.exists():
            raise FileNotFoundError(f"VTT file does not exist: {vtt_path}")

        # Patterns
        timestamp_pattern = re.compile(
            r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}"
        )
        tag_pattern = re.compile(r"<.*?>")  # HTML tags

        paragraphs = []
        current_paragraph = []
        last_line = ""

        try:
            async with aiofiles.open(vtt_path, "r", encoding="utf-8") as f:
                async for line in f:
                    line = line.strip()

                    # Paragraph break
                    if not line:
                        if current_paragraph:
                            paragraphs.append(" ".join(current_paragraph))
                            current_paragraph = []
                        continue

                    # Skip metadata headers
                    if line.upper().startswith("WEBVTT") or line.startswith("NOTE"):
                        continue

                    # Skip timestamps
                    if timestamp_pattern.search(line):
                        continue

                    # Remove HTML/VTT style tags
                    line = re.sub(tag_pattern, "", line)

                    # Remove speaker labels like "SPEAKER: Hello"
                    if ":" in line and len(line.split(":")[0]) < 25:
                        parts = line.split(":", 1)
                        if parts[0].isupper() or parts[0].istitle():
                            line = parts[1].strip()

                    # Deduplicate consecutive repeat lines (very common in auto subs)
                    if line == last_line:
                        continue

                    last_line = line
                    current_paragraph.append(line)

            # Write out last paragraph
            if current_paragraph:
                paragraphs.append(" ".join(current_paragraph))

            async with aiofiles.open(txt_path, "w", encoding="utf-8") as f:
                await f.write("\n\n".join(paragraphs))

            logger.info(f"Successfully converted subtitle to: {txt_path}")
            return txt_path

        except Exception as e:
            logger.error(f"Error converting VTT to TXT: {e}", exc_info=True)
            raise YtDownloadError(f"VTT conversion failed: {str(e)}")

    async def clean_folder(self, folder_path: Path) -> int:
        """Scan and convert all .vtt files inside a folder (recursively)."""
        logger.info(f"Scanning folder for subtitle conversion: {folder_path}")
        if not folder_path.exists():
            return 0

        converted_count = 0
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.endswith(".vtt"):
                    vtt_file = Path(root) / file
                    try:
                        await self.clean_vtt_to_txt(vtt_file)
                        converted_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to clean subtitle {vtt_file}: {e}")
        
        return converted_count
