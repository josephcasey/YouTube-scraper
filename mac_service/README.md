# Mac transcript proxy

An always-on HTTP service that runs on your MacBook and fetches YouTube
transcripts from your **residential IP** — which YouTube allows — then hands them
back to a remote, IP-blocked environment (like Claude Code on the web) over a
**free Tailscale tunnel**.

```
[remote Claude session]  ──HTTPS──▶  [Tailscale tunnel]  ──▶  [this service on your Mac]  ──▶  YouTube ✓
   (datacenter IP, blocked)            (free, stable URL)        (your home IP, allowed)
```

It's a thin wrapper around the repo's existing `mcp_server.youtube` functions —
no new fetch logic, just a network door with auth.

---

## 1. Clone & install dependencies

```bash
git clone <your-repo-url> YouTube-scraper
cd YouTube-scraper
python3 -m pip install -e .          # installs yt-dlp, youtube-transcript-api, requests
```

## 2. Set the bearer token

The service **refuses to start without a token** (it sits behind a public tunnel,
so auth is mandatory). Use the token you were given, or generate one:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Write it to the gitignored token file:

```bash
echo 'YOUR_TOKEN_HERE' > mac_service/.token
```

> `mac_service/.token`, `*.token`, and `.env` are all gitignored — the secret
> never enters version control. The **same** token also goes into the remote
> environment's config as `YOUTUBE_PROXY_TOKEN` (see step 5), never into the repo.

## 3. Run as an always-on service

```bash
./mac_service/install-macos.sh
```

This installs a `launchd` agent (`com.youtube-proxy`) that starts on login and
restarts on crash. Verify it's up:

```bash
curl -s http://127.0.0.1:8787/health
# {"status": "ok", "service": "youtube-proxy"}
```

Logs live in `~/Library/Logs/youtube-proxy/`. To remove it later:
`./mac_service/install-macos.sh uninstall`.

To run it in the foreground instead (for a quick test):
`python3 -m mac_service.server`

## 4. Expose it with Tailscale (free, stable URL — no domain to buy)

```bash
brew install tailscale
sudo tailscaled install-system-daemon      # always-on daemon, survives reboot
sudo tailscale up                          # log in (free personal account)

# One-time: enable MagicDNS + HTTPS at https://login.tailscale.com/admin/dns
```

Then pick **one** exposure mode:

| Mode | Command | Reachable by | Use when |
|------|---------|--------------|----------|
| **Funnel** (public) | `tailscale funnel --bg 8787` | anyone with the URL **+ token** | simplest; remote env just makes a plain HTTPS call |
| **Serve** (private) | `tailscale serve --bg 8787` | only devices on your tailnet | most secure; no public URL exists |

Both print a stable `https://<your-mac>.<your-tailnet>.ts.net` URL that survives
reboots. Funnel is the easy default; the service code is identical for both, so
you can switch any time. Turn exposure off with `tailscale funnel off`.

## 5. Wire up the remote environment

In your Claude Code on the web **environment configuration** (not the repo), add
two secrets:

```
YOUTUBE_PROXY_URL    = https://<your-mac>.<your-tailnet>.ts.net
YOUTUBE_PROXY_TOKEN  = <the same token from step 2>
```

Every container that spins up then has them in its environment, and the
cloud-side `proxy_client.py` picks them up automatically — nothing committed.

---

## Security model

- **Bearer token** on every endpoint except `/health`; constant-time compare.
- **YouTube-only validation** — video params are parsed by `extract_video_id`
  (11-char IDs only) and playlist URLs are restricted to `youtube.com`/`youtu.be`.
  This is deliberately **not** a general-purpose proxy, so it can't be used for
  SSRF or to relay arbitrary traffic.
- **Localhost bind** — the Python server only listens on `127.0.0.1`; the
  Tailscale tunnel is the single front door.
- **Rate limit** — `YOUTUBE_PROXY_RATE_LIMIT` requests/min (default 60) to blunt
  abuse if a token ever leaks.
- **Realistic blast radius** — even in a worst case, the only capability exposed
  is "fetch public YouTube transcripts via this IP." Rotate the token by editing
  `mac_service/.token` (+ the env config) and restarting; no git history to scrub.

## Endpoints

All return JSON. All except `/health` require `Authorization: Bearer <token>`.

| Route | Params | Returns |
|-------|--------|---------|
| `GET /health` | — | liveness check (no auth) |
| `GET /info` | `video` | title, duration, languages, word count, chunk layout |
| `GET /transcript` | `video`, `language=en` | full transcript: segments + timestamped text |
| `GET /search` | `video`, `query`, `language=en`, `max_results=20`, `context_lines=3` | matching lines with context |
| `GET /playlist` | `url` | all videos in a YouTube playlist |
