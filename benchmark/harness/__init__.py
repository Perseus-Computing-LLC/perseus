"""Harness package: A/B replay + load ramp + edge cases.

For the offline suite we generate SYNTHETIC requests rather than sampling
real production logs (which the homelab does not have). Records are tagged
synthetic: true.
"""
