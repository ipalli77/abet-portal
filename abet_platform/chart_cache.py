"""Bounded process-local chart cache, keyed after authorization and DB reads."""
from collections import OrderedDict
import hashlib
import json
import threading
import time

from flask import current_app, g, session

_RENDER_LOCK = threading.RLock()  # Matplotlib's pyplot state is not thread-safe.


def render_scoped_charts(records, names, renderer, *, campus_group="term", output_format="png", dpi=150, export_caption=""):
    if not names or not records:
        return {}
    # Include values (not just timestamps) so edits, approvals, campus moves and
    # revoked permissions invalidate immediately on the next authorized read.
    payload = {"database": current_app.config["DATABASE"], "user": g.user["id"],
               "organization": session.get("organization_id"), "program": session.get("program_id"),
               "role": g.membership["role"], "edition": current_app.config.get("EDITION"),
               "records": [dict(r) for r in records], "names": sorted(names),
               "group": campus_group, "format": output_format, "dpi": dpi, "caption": export_caption}
    key = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    with _RENDER_LOCK:
        cache = current_app.extensions.setdefault("scoped_chart_cache", OrderedDict())
        now = time.monotonic()
        for old_key in list(cache):
            if now - cache[old_key][0] > 300:
                del cache[old_key]
        if key in cache:
            cache.move_to_end(key)
            return cache[key][1]
        result = renderer(records, campus_group=campus_group, chart_names=names,
                          output_format=output_format, dpi=dpi, export_caption=export_caption)
        size = len(json.dumps(result, default=str))
        # Keep worker memory bounded even with many course/PI combinations.
        limit = 32 * 1024 * 1024
        while cache and (len(cache) >= 16 or sum(v[2] for v in cache.values()) + size > limit):
            cache.popitem(last=False)
        if size <= limit:
            cache[key] = (time.monotonic(), result, size)
        return result
