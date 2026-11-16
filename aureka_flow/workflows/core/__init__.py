"""Software alpha: measurements are not biological gate validation."""

from aureka_flow import __version__

from .core import analyze_fcs, demo, inspect_fcs, summarize_events, validate_config

__all__ = ["analyze_fcs", "demo", "inspect_fcs", "summarize_events", "validate_config"]
