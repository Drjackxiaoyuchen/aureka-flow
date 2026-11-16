"""Descriptive, explicitly joined FACS experiment reports; not affinity inference."""

from .analysis import analyze, synthetic_manifest
from .validation import ValidationError

from aureka_flow import __version__
__all__ = ["analyze", "synthetic_manifest", "ValidationError"]
