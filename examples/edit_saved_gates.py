"""Synthetic parent/child edit and undo/redo; no experimental files required.

Run from the repository: python examples/edit_saved_gates.py
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flowio
import numpy as np

from aureka_flow.engine import AnalysisEngine, GateEditSpec, GateSpec


def main():
    output = io.BytesIO()
    values = np.arange(1200, dtype=float)
    flowio.create_fcs(output, np.column_stack([values, values * 2]).ravel().tolist(), ["X", "Y"])
    engine = AnalysisEngine()
    uid = engine.load(output.getvalue(), "synthetic-edit-reference.fcs")["id"]
    for name, parent, bounds in [("Parent", "root", [100, 900, None, None]),
                                 ("Child", "Parent", [200, 800, None, None])]:
        engine.add_gate(GateSpec(name=name, parent=parent, kind="range", x={"channel": "X"}, bounds=bounds), uid)
    rec = engine.record(uid)

    def counts(label):
        rows = engine.populations(rec)
        print(label + ": " + ", ".join(f"{p['name']}={p['count']}" for p in rows))

    print("Synthetic reference only; no affinity or function is inferred.")
    counts("Before")
    engine.edit_gate("Parent", GateEditSpec(revision=engine.revision, name="Reviewed parent",
                                           bounds=(650, 1000, None, None)), uid)
    counts("Edited")
    assert np.flatnonzero(engine.mask(rec, "Child")).tolist() == list(range(650, 800))
    engine.navigate_gate_history("undo", engine.revision)
    counts("Undo")
    engine.navigate_gate_history("redo", engine.revision)
    counts("Redo")
    print("FCS SHA-256:", rec.digest)


if __name__ == "__main__":
    main()
