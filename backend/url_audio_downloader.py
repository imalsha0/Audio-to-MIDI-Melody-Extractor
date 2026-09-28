"""
Universal Audio Downloader using yt-dlp with fallback to direct HTTP downloads.
Supports YouTube, SoundCloud, TikTok, Facebook, Instagram, Google Drive, direct MP3/WAV links, etc.
"""

import os
import re
import urllib.parse
from pathlib import Path
import httpx
import yt_dlp


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.replace(" ", "_")
    return name[:50] or "downloaded_audio"


def download_audio_from_url(url: str, output_dir: Path) -> Path:
    """
    Downloads audio from any web URL (YouTube, SoundCloud, direct MP3 link, etc.)
    and saves it to output_dir as a WAV or MP3 file. Returns Path to downloaded file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Check if it's a direct audio file link (.mp3, .wav, .m4a, .flac, .ogg, .aac)
    parsed = urllib.parse.urlparse(url)
    path_lower = parsed.path.lower()
    audio_extensions = [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"]

    if any(path_lower.endswith(ext) for ext in audio_extensions):
        ext = Path(parsed.path).suffix or ".mp3"
        filename = sanitize_filename(Path(parsed.path).stem) + ext
        out_path = output_dir / filename

        print(f"[Direct Download] Downloading {url} -> {out_path}")
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
            response.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
        return out_path

    # 2. Use yt-dlp for media sites (YouTube, SoundCloud, TikTok, Vimeo, etc.)
    out_template = str(output_dir / "%(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "extract_flat": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # The postprocessor changes the extension to .mp3
            base, _ = os.path.splitext(filename)
            expected_mp3 = Path(f"{base}.mp3")

            if expected_mp3.exists():
                return expected_mp3

            # Fallback search in output_dir
            for item in output_dir.glob("*"):
                if item.is_file() and item.suffix.lower() in [".mp3", ".wav", ".m4a", ".webm"]:
                    return item
            raise FileNotFoundError("Could not locate downloaded audio file.")
    except Exception as e:
        # Retry with simpler yt-dlp config (without ffmpeg postprocessing if ffmpeg is missing)
        ydl_opts_simple = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts_simple) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if Path(filename).exists():
                return Path(filename)
            raise RuntimeError(f"Failed to download audio from URL: {str(e)}")
