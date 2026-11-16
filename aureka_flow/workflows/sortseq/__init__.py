"""Original sort-bin/count linkage utilities. Not an affinity estimator."""
from .linkage import ValidationError, link_experiment

from aureka_flow import __version__
__all__ = ["ValidationError", "link_experiment"]
