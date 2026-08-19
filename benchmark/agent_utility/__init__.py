"""Public entry points for the paired coding-agent utility protocol."""
from . import protocol
from .runner import run_synthetic_pair

__all__ = ["protocol", "run_synthetic_pair"]
