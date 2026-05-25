"""Edge tests: max-context, malformed, spike injector, toxiproxy scenarios.
For the offline suite these are referenced; real network-dependent tests
are skipped with explicit reason strings.
"""
def run_all() -> dict:
    return {
        "max_context": {"skipped": True, "reason": "no live provider"},
        "malformed": {"covered_by": "C2 in adversarial_extended"},
        "spike_injector": {"covered_by": "Phase 2 wave 4 in swarm_chaos"},
        "toxiproxy_scenarios": {"skipped": True, "reason": "toxiproxy + live provider not configured"},
    }
