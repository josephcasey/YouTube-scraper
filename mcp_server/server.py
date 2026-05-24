"""YouTube Transcript MCP Server."""

import asyncio
import json
import os

from mcp.server.fastmcp import FastMCP

from .chunker import chunk_transcript, get_chunk_text, search_transcript
from .youtube import (
    extract_video_id,
    fetch_playlist_videos,
    fetch_transcript,
    fetch_video_info,
    list_transcript_languages,
    transcript_to_text,
)

_MAX_FULL_WORDS = int(os.environ.get("YOUTUBE_MCP_MAX_FULL_WORDS", "40000"))
_DEFAULT_CHUNK_MINUTES = int(os.environ.get("YOUTUBE_MCP_DEFAULT_CHUNK_MINUTES", "30"))

mcp = FastMCP("youtube-transcript")


@mcp.tool()
async def get_playlist_videos(playlist_url: str) -> str:
    """List all videos in a YouTube playlist (IDs, titles, URLs — not transcripts)."""
    try:
        videos = await asyncio.to_thread(fetch_playlist_videos, playlist_url)
    except Exception as exc:
        return f"ERROR: {exc}"
    result = {
        "total": len(videos),
        "videos": [{"position": i + 1, **v} for i, v in enumerate(videos)],
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def get_video_transcript_info(video_url_or_id: str) -> str:
    """
    Get metadata about a video's transcript: title, duration, word count,
    available languages, and chunk layout for navigation.
    Call this before fetching transcript text.
    """
    try:
        video_id = extract_video_id(video_url_or_id)
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        info, langs, segments = await asyncio.gather(
            asyncio.to_thread(fetch_video_info, video_id),
            asyncio.to_thread(list_transcript_languages, video_id),
            asyncio.to_thread(fetch_transcript, video_id),
        )
    except Exception as exc:
        return f"ERROR: {exc}"

    if segments is None:
        return f"ERROR: No transcript available for {video_id}"

    total_words = sum(len(s["text"].split()) for s in segments)
    chunks = chunk_transcript(segments, _DEFAULT_CHUNK_MINUTES)

    result = {
        "video_id": video_id,
        "title": info["title"],
        "duration_seconds": info["duration_seconds"],
        "total_words": total_words,
        "total_segments": len(segments),
        "available_languages": langs,
        "chunks": [
            {
                "chunk_index": c["chunk_index"],
                "start_label": c["start_label"],
                "end_label": c["end_label"],
                "word_count": c["word_count"],
            }
            for c in chunks
        ],
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def get_video_transcript_chunk(
    video_url_or_id: str,
    chunk_index: int,
    chunk_duration_minutes: int = 30,
    language: str = "en",
) -> str:
    """
    Fetch one time-window of a video's transcript as timestamped text.
    Use get_video_transcript_info first to see how many chunks exist.
    """
    try:
        video_id = extract_video_id(video_url_or_id)
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        segments = await asyncio.to_thread(fetch_transcript, video_id, [language])
    except Exception as exc:
        return f"ERROR: {exc}"
    if segments is None:
        return f"ERROR: No transcript available for {video_id}"

    chunks_meta = chunk_transcript(segments, chunk_duration_minutes)
    if chunk_index < 0 or chunk_index >= len(chunks_meta):
        return f"ERROR: chunk_index {chunk_index} out of range (0–{len(chunks_meta) - 1})"

    text = get_chunk_text(segments, chunk_index, chunk_duration_minutes)
    meta = chunks_meta[chunk_index]
    header = (
        f"[Chunk {chunk_index + 1}/{len(chunks_meta)}: "
        f"{meta['start_label']}–{meta['end_label']}, ~{meta['word_count']} words]"
    )
    return f"{header}\n\n{text}"


@mcp.tool()
async def get_full_transcript(video_url_or_id: str, language: str = "en") -> str:
    """
    Fetch the complete transcript of a YouTube video as timestamped text.
    WARNING: Long videos can return 50,000+ words. Use get_video_transcript_chunk for those.
    """
    try:
        video_id = extract_video_id(video_url_or_id)
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        segments = await asyncio.to_thread(fetch_transcript, video_id, [language])
    except Exception as exc:
        return f"ERROR: {exc}"
    if segments is None:
        return f"ERROR: No transcript available for {video_id}"

    total_words = sum(len(s["text"].split()) for s in segments)
    if total_words > _MAX_FULL_WORDS:
        chunks_meta = chunk_transcript(segments)
        return (
            f"ERROR: Transcript is too long ({total_words:,} words) for a single response. "
            f"Use get_video_transcript_chunk with chunk_index 0–{len(chunks_meta) - 1} instead."
        )

    text = transcript_to_text(segments)
    return f"[{video_id} — {total_words:,} words]\n\n{text}"


@mcp.tool()
async def search_video_transcript(
    video_url_or_id: str,
    query: str,
    max_results: int = 20,
    context_lines: int = 3,
    language: str = "en",
) -> str:
    """
    Search a video's transcript for a keyword or phrase.
    Returns matching lines with surrounding context and timestamps.
    timestamp_seconds can be used to build YouTube ?t=N deep-links.
    """
    try:
        video_id = extract_video_id(video_url_or_id)
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        segments = await asyncio.to_thread(fetch_transcript, video_id, [language])
    except Exception as exc:
        return f"ERROR: {exc}"
    if segments is None:
        return f"ERROR: No transcript available for {video_id}"

    result = search_transcript(segments, query, max_results, context_lines)
    return json.dumps(result, ensure_ascii=False)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="YouTube Transcript MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8080, help="Port for SSE transport")
    parser.add_argument("--host", default="127.0.0.1", help="Host for SSE transport")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
