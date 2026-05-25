"""Batch metrics tracker (stub for offline suite)."""
def summarize(records: list[dict]) -> dict:
    if not records:
        return {"batches": 0, "avg_batch_size": 0}
    # Group by 1-second buckets as a proxy for batch dispatch windows.
    buckets: dict[int, int] = {}
    for r in records:
        ts = r.get("timestamp_request_start_utc", "")
        key = ts[:19]  # ISO second
        buckets[key] = buckets.get(key, 0) + 1
    return {
        "batches": len(buckets),
        "avg_batch_size": sum(buckets.values()) / max(len(buckets), 1),
        "max_batch_size": max(buckets.values()) if buckets else 0,
    }
