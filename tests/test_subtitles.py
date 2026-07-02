import pytest
from pathlib import Path
from yt_download_enterprise.services.subtitles import SubtitleService


@pytest.mark.asyncio
async def test_vtt_to_txt_cleaning(tmp_path: Path):
    """Test that WebVTT files are correctly parsed and cleaned of timestamps/tags."""
    vtt_content = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:04.000
<c>Hello</c> World!

00:00:04.000 --> 00:00:07.000
SPEAKER: Hello World!

00:00:07.000 --> 00:00:10.000
SPEAKER: Hello World!

00:00:10.000 --> 00:00:12.000
Let's wrap this up.
"""
    # Create temp VTT file
    vtt_file = tmp_path / "test_captions.vtt"
    vtt_file.write_text(vtt_content, encoding="utf-8")

    service = SubtitleService()
    txt_file = await service.clean_vtt_to_txt(vtt_file)

    assert txt_file.exists()
    
    # Read cleaned content
    cleaned_content = txt_file.read_text(encoding="utf-8")
    
    # Verify that:
    # 1. Timestamps are removed
    assert "00:00:01.000" not in cleaned_content
    # 2. VTT styling tags are removed
    assert "<c>" not in cleaned_content
    assert "</c>" not in cleaned_content
    # 3. Speaker labels are removed
    assert "SPEAKER:" not in cleaned_content
    # 4. Consecutive duplicates are removed ("Hello World!" appears once)
    assert cleaned_content.count("Hello World!") == 1
    # 5. Clean text is preserved
    assert "Let's wrap this up." in cleaned_content
