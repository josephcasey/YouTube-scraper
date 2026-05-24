"""Core YouTube fetching logic — no MCP dependency."""

import os
import re
import ssl
import sys

import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

if os.environ.get("YOUTUBE_MCP_DISABLE_SSL", "true").lower() in ("1", "true", "yes"):
    ssl._create_default_https_context = ssl._create_unverified_context


def _make_http_client() -> requests.Session:
    session = requests.Session()
    session.verify = False
    return session


_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})")


def extract_video_id(url_or_id: str) -> str:
    """Return the 11-char video ID from a URL or bare ID string."""
    url_or_id = url_or_id.strip()
    m = _VIDEO_ID_RE.search(url_or_id)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id
    raise ValueError(f"Cannot extract video ID from: {url_or_id!r}")


def fetch_playlist_videos(playlist_url: str) -> list[dict]:
    """Return [{id, title, url}] for all videos in a playlist."""
    ydl_opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
    videos = []
    for entry in info.get("entries", []):
        if entry and entry.get("id"):
            videos.append({
                "id": entry["id"],
                "title": entry.get("title", entry["id"]),
                "url": f"https://www.youtube.com/watch?v={entry['id']}",
            })
    return videos


def fetch_video_info(video_id: str) -> dict:
    """Return {id, title, duration_seconds} for a single video."""
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    return {
        "id": video_id,
        "title": info.get("title", video_id),
        "duration_seconds": info.get("duration", 0),
    }


def list_transcript_languages(video_id: str) -> dict:
    """Return {manually_created: [...], auto_generated: [...]} language codes."""
    api = YouTubeTranscriptApi(http_client=_make_http_client())
    transcript_list = api.list(video_id)
    manually = []
    auto = []
    for t in transcript_list:
        if t.is_generated:
            auto.append(t.language_code)
        else:
            manually.append(t.language_code)
    return {"manually_created": manually, "auto_generated": auto}


def fetch_transcript(video_id: str, languages: list[str] | None = None) -> list[dict] | None:
    """
    Fetch transcript segments [{text, start, duration}] or None on failure.
    Tries `languages` in order, then falls back to any available language.
    """
    if languages is None:
        languages = ["en"]
    try:
        api = YouTubeTranscriptApi(http_client=_make_http_client())
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_transcript(languages)
        except Exception:
            transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        return [{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched]
    except (NoTranscriptFound, TranscriptsDisabled):
        return None
    except Exception as exc:
        print(f"Warning: unexpected error fetching transcript for {video_id}: {exc}", file=sys.stderr)
        return None


def transcript_to_text(segments: list[dict]) -> str:
    """Join segments into timestamped plain text."""
    lines = []
    for seg in segments:
        start = seg.get("start", 0)
        minutes, seconds = divmod(int(start), 60)
        hours, minutes = divmod(minutes, 60)
        ts = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]" if hours else f"[{minutes:02d}:{seconds:02d}]"
        lines.append(f"{ts} {seg['text']}")
    return "\n".join(lines)
