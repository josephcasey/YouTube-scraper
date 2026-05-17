#!/usr/bin/env python3
"""
Scrape YouTube transcripts for DDRJake's "Bagpipes in Bordeaux" EU5 playlist.

Usage:
    python3 scrape_transcripts.py [--output-dir OUTPUT_DIR] [--format {json,txt,both}]

Outputs one file per video in the specified format.
"""

import argparse
import json
import os
import re
import ssl
import sys
import time

import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

# The sandbox environment uses a self-signed proxy certificate; disable SSL verification globally.
ssl._create_default_https_context = ssl._create_unverified_context

def _make_http_client() -> requests.Session:
    """Return a requests Session with SSL verification disabled for the sandbox proxy."""
    session = requests.Session()
    session.verify = False
    return session

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLm0MDLKuRDrmX27Fs1LOK07c_uRbzV5Oh"


def safe_filename(title: str) -> str:
    """Convert a video title to a safe filename."""
    title = re.sub(r'[\\/*?:"<>|]', "", title)
    title = re.sub(r"\s+", "_", title.strip())
    return title[:100]


def fetch_playlist_videos(playlist_url: str) -> list[dict]:
    """Return a list of {id, title, url} dicts for all videos in the playlist."""
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


def fetch_transcript(video_id: str) -> list[dict] | None:
    """
    Fetch the transcript for a single video.
    Tries English first, then any available language.
    Returns a list of {text, start, duration} dicts, or None on failure.
    """
    try:
        api = YouTubeTranscriptApi(http_client=_make_http_client())
        transcript_list = api.list(video_id)
        # Prefer manually created English, then auto-generated English, then anything
        try:
            transcript = transcript_list.find_transcript(["en"])
        except Exception:
            transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        # Convert FetchedTranscript to plain list of dicts
        return [{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched]
    except (NoTranscriptFound, TranscriptsDisabled):
        return None
    except Exception as exc:
        print(f"  Warning: unexpected error fetching transcript: {exc}", file=sys.stderr)
        return None


def transcript_to_text(segments: list[dict]) -> str:
    """Join transcript segments into a readable plain-text string with timestamps."""
    lines = []
    for seg in segments:
        start = seg.get("start", 0)
        minutes, seconds = divmod(int(start), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            ts = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
        else:
            ts = f"[{minutes:02d}:{seconds:02d}]"
        lines.append(f"{ts} {seg['text']}")
    return "\n".join(lines)


def save_json(path: str, video: dict, segments: list[dict]) -> None:
    data = {
        "id": video["id"],
        "title": video["title"],
        "url": video["url"],
        "transcript": segments,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_txt(path: str, video: dict, segments: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Title: {video['title']}\n")
        f.write(f"URL:   {video['url']}\n")
        f.write(f"ID:    {video['id']}\n")
        f.write("\n" + "=" * 60 + "\n\n")
        f.write(transcript_to_text(segments))
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default="transcripts", help="Directory to save transcripts (default: transcripts/)")
    parser.add_argument("--format", choices=["json", "txt", "both"], default="both", help="Output format (default: both)")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between requests (default: 1.0)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Fetching playlist: {PLAYLIST_URL}")
    videos = fetch_playlist_videos(PLAYLIST_URL)
    print(f"Found {len(videos)} video(s)\n")

    results = {"success": [], "failed": []}

    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {video['title']}")
        segments = fetch_transcript(video["id"])

        if segments is None:
            print("  No transcript available — skipping")
            results["failed"].append(video)
            continue

        base = os.path.join(args.output_dir, f"{i:02d}_{safe_filename(video['title'])}")

        if args.format in ("json", "both"):
            save_json(f"{base}.json", video, segments)
        if args.format in ("txt", "both"):
            save_txt(f"{base}.txt", video, segments)

        word_count = sum(len(s["text"].split()) for s in segments)
        print(f"  Saved — {len(segments)} segments, ~{word_count} words")
        results["success"].append(video)

        if i < len(videos):
            time.sleep(args.delay)

    print(f"\nDone. {len(results['success'])} transcripts saved to '{args.output_dir}/'")
    if results["failed"]:
        print(f"No transcript found for {len(results['failed'])} video(s):")
        for v in results["failed"]:
            print(f"  - {v['title']} ({v['url']})")


if __name__ == "__main__":
    main()
