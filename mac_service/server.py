"""
Always-on YouTube transcript service for your Mac.

Runs a small HTTP server (localhost-only) that wraps the existing
`mcp_server.youtube` functions. Designed to sit behind a Tailscale Funnel/Serve
tunnel so a remote, IP-blocked environment can delegate YouTube fetches to your
residential IP.

Security model (see mac_service/README.md):
  * Bearer-token auth on every endpoint except /health (constant-time compare).
  * Strict YouTube-only input validation — this is NOT a general-purpose proxy.
  * Binds to 127.0.0.1 only; the tunnel is the single front door.
  * Simple global rate limit to blunt abuse if a token ever leaks.

Run:
    python3 -m mac_service.server
"""

import hmac
import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from mcp_server.chunker import chunk_transcript, search_transcript
from mcp_server.youtube import (
    extract_video_id,
    fetch_playlist_videos,
    fetch_transcript,
    fetch_video_info,
    list_transcript_languages,
    transcript_to_text,
)

HOST = os.environ.get("YOUTUBE_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("YOUTUBE_PROXY_PORT", "8787"))
RATE_LIMIT_PER_MIN = int(os.environ.get("YOUTUBE_PROXY_RATE_LIMIT", "60"))

_ALLOWED_HOSTS = ("youtube.com", "youtu.be")


def _load_token() -> str:
    """
    Resolve the bearer token, in order:
      1. $YOUTUBE_PROXY_TOKEN
      2. file at $YOUTUBE_PROXY_TOKEN_FILE
      3. mac_service/.token  (gitignored)
    Refuse to start if none is found — an unauthenticated public endpoint is unsafe.
    """
    token = os.environ.get("YOUTUBE_PROXY_TOKEN", "").strip()
    if token:
        return token

    path = os.environ.get("YOUTUBE_PROXY_TOKEN_FILE", "").strip()
    if not path:
        path = os.path.join(os.path.dirname(__file__), ".token")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token

    sys.exit(
        "ERROR: no bearer token found. Set YOUTUBE_PROXY_TOKEN, or write one to "
        "mac_service/.token (gitignored). Refusing to start without auth."
    )


TOKEN = _load_token()


class _RateLimiter:
    """Global sliding-window limiter (all callers share, since they arrive via one tunnel)."""

    def __init__(self, max_per_min: int):
        self.max = max_per_min
        self.hits: deque[float] = deque()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self.lock:
            while self.hits and now - self.hits[0] > 60.0:
                self.hits.popleft()
            if len(self.hits) >= self.max:
                return False
            self.hits.append(now)
            return True


_limiter = _RateLimiter(RATE_LIMIT_PER_MIN)


def _validate_playlist_url(url: str) -> str:
    """Allow only YouTube playlist URLs — blocks SSRF / open-proxy abuse via yt-dlp."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"Refusing non-YouTube URL: {url!r}")
    return url.strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "youtube-proxy/1.0"

    # --- helpers -------------------------------------------------------------

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return hmac.compare_digest(header[len(prefix):], TOKEN)

    def log_message(self, fmt, *args):  # keep logs quiet & secret-free
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- routing -------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if route == "/health":
            self._send(200, {"status": "ok", "service": "youtube-proxy"})
            return

        if not self._authed():
            self._send(401, {"error": "unauthorized"})
            return

        if not _limiter.allow():
            self._send(429, {"error": "rate limited", "limit_per_min": RATE_LIMIT_PER_MIN})
            return

        try:
            handler = {
                "/info": self._info,
                "/transcript": self._transcript,
                "/search": self._search,
                "/playlist": self._playlist,
            }.get(route)
            if handler is None:
                self._send(404, {"error": f"unknown route {route!r}"})
                return
            handler(params)
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — surface a clean message, log detail
            sys.stderr.write(f"handler error on {route}: {exc!r}\n")
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    # --- endpoints -----------------------------------------------------------

    def _info(self, params: dict):
        video_id = extract_video_id(params.get("video", ""))
        info = fetch_video_info(video_id)
        langs = list_transcript_languages(video_id)
        segments = fetch_transcript(video_id)
        if segments is None:
            self._send(404, {"error": f"no transcript for {video_id}"})
            return
        total_words = sum(len(s["text"].split()) for s in segments)
        chunks = chunk_transcript(segments)
        self._send(200, {
            "video_id": video_id,
            "title": info["title"],
            "duration_seconds": info["duration_seconds"],
            "total_words": total_words,
            "total_segments": len(segments),
            "available_languages": langs,
            "chunks": chunks,
        })

    def _transcript(self, params: dict):
        video_id = extract_video_id(params.get("video", ""))
        language = params.get("language", "en")
        segments = fetch_transcript(video_id, [language])
        if segments is None:
            self._send(404, {"error": f"no transcript for {video_id}"})
            return
        self._send(200, {
            "video_id": video_id,
            "language": language,
            "total_segments": len(segments),
            "total_words": sum(len(s["text"].split()) for s in segments),
            "segments": segments,
            "text": transcript_to_text(segments),
        })

    def _search(self, params: dict):
        video_id = extract_video_id(params.get("video", ""))
        query = params.get("query", "")
        if not query:
            raise ValueError("missing 'query' parameter")
        language = params.get("language", "en")
        max_results = int(params.get("max_results", "20"))
        context_lines = int(params.get("context_lines", "3"))
        segments = fetch_transcript(video_id, [language])
        if segments is None:
            self._send(404, {"error": f"no transcript for {video_id}"})
            return
        self._send(200, search_transcript(segments, query, max_results, context_lines))

    def _playlist(self, params: dict):
        url = _validate_playlist_url(params.get("url", ""))
        videos = fetch_playlist_videos(url)
        self._send(200, {"total": len(videos), "videos": videos})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"youtube-proxy listening on http://{HOST}:{PORT} "
        f"(rate limit {RATE_LIMIT_PER_MIN}/min) — token loaded, len={len(TOKEN)}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
