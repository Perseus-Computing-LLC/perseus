"""Load profile descriptor (no live Locust dependency).

Returns the ramp profile the suite would apply against a real provider.
Used by the orchestrator to record the intended load shape and by the
gate runner to assert recovery shape.
"""
PROFILE = [
    {"phase": "baseline",  "concurrency": 5,   "duration_s": 300, "purpose": "establish P50/P99 floor"},
    {"phase": "ramp",      "concurrency": 50,  "duration_s": 600, "purpose": "find knee"},
    {"phase": "sustained", "concurrency": 50,  "duration_s": 900, "purpose": "queue buildup"},
    {"phase": "spike",     "concurrency": 200, "duration_s": 60,  "purpose": "rate limit + fallbacks"},
    {"phase": "recovery",  "concurrency": 10,  "duration_s": 300, "purpose": "queue drain"},
]
