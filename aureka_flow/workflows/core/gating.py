"""Compensation/gating API requiring explicit scientific choices from the caller."""

from .core import analyze_fcs, summarize_events, validate_config

__all__ = ["analyze_fcs", "summarize_events", "validate_config"]
