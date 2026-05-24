"""Chunking and search utilities for large transcripts."""


def _seconds_to_label(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def chunk_transcript(segments: list[dict], chunk_minutes: int = 30) -> list[dict]:
    """
    Split segments into fixed-duration windows.
    Returns chunk metadata only (no text): [{chunk_index, start_seconds,
    end_seconds, start_label, end_label, word_count, segment_count}].
    """
    if not segments:
        return []

    window = chunk_minutes * 60.0
    chunks = []
    chunk_index = 0
    window_start = 0.0

    while True:
        window_end = window_start + window
        bucket = [s for s in segments if window_start <= s["start"] < window_end]
        if not bucket:
            break
        word_count = sum(len(s["text"].split()) for s in bucket)
        chunks.append({
            "chunk_index": chunk_index,
            "start_seconds": bucket[0]["start"],
            "end_seconds": bucket[-1]["start"] + bucket[-1].get("duration", 0),
            "start_label": _seconds_to_label(bucket[0]["start"]),
            "end_label": _seconds_to_label(bucket[-1]["start"]),
            "word_count": word_count,
            "segment_count": len(bucket),
        })
        chunk_index += 1
        window_start = window_end

        if window_end > segments[-1]["start"]:
            break

    return chunks


def get_chunk_text(segments: list[dict], chunk_index: int, chunk_minutes: int = 30) -> str:
    """Return timestamped plain text for one chunk window."""
    window = chunk_minutes * 60.0
    window_start = chunk_index * window
    window_end = window_start + window
    bucket = [s for s in segments if window_start <= s["start"] < window_end]
    if not bucket:
        return ""

    lines = []
    for seg in bucket:
        start = seg["start"]
        m, s = divmod(int(start), 60)
        h, m = divmod(m, 60)
        ts = f"[{h:02d}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"
        lines.append(f"{ts} {seg['text']}")
    return "\n".join(lines)


def search_transcript(
    segments: list[dict],
    query: str,
    max_results: int = 20,
    context_lines: int = 3,
) -> dict:
    """
    Case-insensitive keyword search across segments.
    Returns {query, total_hits, returned, results: [{timestamp,
    timestamp_seconds, matched_text, context}]}.
    """
    q = query.lower()
    hits = [i for i, s in enumerate(segments) if q in s["text"].lower()]

    results = []
    for idx in hits[:max_results]:
        seg = segments[idx]
        start = seg["start"]
        m, s = divmod(int(start), 60)
        h, m = divmod(m, 60)
        ts = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

        ctx_start = max(0, idx - context_lines)
        ctx_end = min(len(segments), idx + context_lines + 1)
        context_text = " … ".join(segments[i]["text"] for i in range(ctx_start, ctx_end))

        results.append({
            "timestamp": ts,
            "timestamp_seconds": int(start),
            "matched_text": seg["text"],
            "context": context_text,
        })

    return {
        "query": query,
        "total_hits": len(hits),
        "returned": len(results),
        "results": results,
    }
