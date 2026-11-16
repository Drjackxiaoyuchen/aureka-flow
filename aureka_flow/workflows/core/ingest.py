"""Ingestion module API; detector reading is separate from experimental identity."""

from .core import inspect_fcs, sha256_file

__all__ = ["inspect_fcs", "sha256_file"]
