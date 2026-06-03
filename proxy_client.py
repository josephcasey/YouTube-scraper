#!/usr/bin/env python3
"""
Cloud-side client for the Mac transcript proxy.

When YouTube blocks this environment's datacenter IP, delegate the fetch to the
always-on service running on your Mac (mac_service/server.py), reached over a
Tailscale tunnel. Reads two values from the environment so nothing is committed:

    YOUTUBE_PROXY_URL    e.g. https://your-mac.your-tailnet.ts.net
    YOUTUBE_PROXY_TOKEN  the shared bearer token

Usage:
    python3 proxy_client.py transcript <video-url-or-id> [--language en]
    python3 proxy_client.py info       <video-url-or-id>
    python3 proxy_client.py search     <video-url-or-id> <query>
    python3 proxy_client.py playlist   <playlist-url>
    python3 proxy_client.py health
"""

import argparse
import json
import os
import sys
from urllib.parse import urlencode

import requests


def _config() -> tuple[str, str]:
    url = os.environ.get("YOUTUBE_PROXY_URL", "").strip().rstrip("/")
    token = os.environ.get("YOUTUBE_PROXY_TOKEN", "").strip()
    if not url:
        sys.exit("ERROR: YOUTUBE_PROXY_URL is not set (point it at your Mac's tunnel URL).")
    if not token:
        sys.exit("ERROR: YOUTUBE_PROXY_TOKEN is not set.")
    return url, token


def call(route: str, params: dict | None = None, *, auth: bool = True, timeout: int = 120) -> dict:
    """GET a route on the Mac proxy and return parsed JSON."""
    url, token = _config()
    headers = {"Authorization": f"Bearer {token}"} if auth else {}
    full = f"{url}{route}"
    if params:
        full = f"{full}?{urlencode(params)}"
    resp = requests.get(full, headers=headers, timeout=timeout)
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise
    if resp.status_code >= 400:
        raise RuntimeError(f"proxy returned {resp.status_code}: {data.get('error', data)}")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("transcript", help="Fetch full transcript")
    p.add_argument("video")
    p.add_argument("--language", default="en")

    p = sub.add_parser("info", help="Fetch transcript metadata")
    p.add_argument("video")

    p = sub.add_parser("search", help="Search a transcript")
    p.add_argument("video")
    p.add_argument("query")
    p.add_argument("--language", default="en")

    p = sub.add_parser("playlist", help="List playlist videos")
    p.add_argument("url")

    sub.add_parser("health", help="Check the proxy is reachable")

    args = parser.parse_args()

    if args.cmd == "health":
        print(json.dumps(call("/health", auth=False), ensure_ascii=False, indent=2))
    elif args.cmd == "transcript":
        data = call("/transcript", {"video": args.video, "language": args.language})
        print(data["text"])
    elif args.cmd == "info":
        print(json.dumps(call("/info", {"video": args.video}), ensure_ascii=False, indent=2))
    elif args.cmd == "search":
        data = call("/search", {"video": args.video, "query": args.query, "language": args.language})
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.cmd == "playlist":
        print(json.dumps(call("/playlist", {"url": args.url}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
