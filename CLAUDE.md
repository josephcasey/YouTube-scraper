# YouTube Transcript Scraper

MCP server that fetches YouTube transcripts via a Tailscale proxy running on the host Mac.
All YouTube requests are routed through the proxy — no direct YouTube access needed.

## MCP Tools

The `youtube-transcript` MCP server exposes five tools. Use them naturally in conversation:

**`get_playlist_videos`** — list all videos in a playlist (IDs, titles, URLs)
```
get_playlist_videos("https://www.youtube.com/playlist?list=...")
```

**`get_video_transcript_info`** — metadata before fetching: title, duration, word count, available languages, chunk layout
```
get_video_transcript_info("https://www.youtube.com/watch?v=VIDEO_ID")
```

**`get_full_transcript`** — complete transcript as timestamped text (errors if >40,000 words — use chunks instead)
```
get_full_transcript("VIDEO_ID", language="en")
```

**`get_video_transcript_chunk`** — one time-window of transcript (default 30-min chunks)
```
get_video_transcript_chunk("VIDEO_ID", chunk_index=0, chunk_duration_minutes=30)
```

**`search_video_transcript`** — keyword/phrase search with surrounding context and timestamps
```
search_video_transcript("VIDEO_ID", "query", max_results=20, context_lines=3)
```

## Proxy

Requests route through a proxy on the host Mac over Tailscale. Configured via env vars:
- `YOUTUBE_PROXY_URL` — Tailscale address of the proxy
- `YOUTUBE_PROXY_TOKEN` — bearer token for auth

Proxy endpoints: `GET /health`, `/transcript?video=ID&language=en`, `/info?video=ID`, `/playlist?url=URL`

If the proxy is unreachable the code falls back to hitting YouTube directly (SSL verification disabled).

## Project Structure

```
mcp_server/
  server.py     # FastMCP server, tool definitions
  youtube.py    # proxy-aware fetch functions (playlist, video info, transcript)
  chunker.py    # transcript chunking and search
scrape_transcripts.py  # standalone CLI scraper for the Bagpipes in Bordeaux playlist
transcripts/           # pre-scraped JSON + TXT files
.mcp.json              # MCP server registration for Claude Code
```

## Running the Server Manually

```bash
# stdio (default, used by Claude Code)
python3 -m mcp_server.server

# SSE for testing
python3 -m mcp_server.server --transport sse --port 8080
```

## Dependencies

```bash
pip install -e .   # installs yt-dlp, youtube-transcript-api, mcp[cli], requests
```
