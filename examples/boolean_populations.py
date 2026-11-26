"""Create a synthetic FCS/project pair for browser Boolean and undo demonstrations."""
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flowio
import numpy as np
from aureka_flow.engine import AnalysisEngine, GateSpec


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "exports/boolean-demo")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Choose an empty output directory; existing files are preserved.")
    values = np.arange(1200, dtype=float)
    buffer = io.BytesIO()
    flowio.create_fcs(buffer, np.column_stack([values, values]).ravel().tolist(), ["X", "Y"])
    engine = AnalysisEngine()
    filename = "synthetic-boolean.fcs"
    uid = engine.load(buffer.getvalue(), filename, "Synthetic Boolean demonstration")["id"]
    for name, parent, lo, hi in [("Parent", "root", 100, 1000), ("A", "Parent", 200, 700), ("B", "Parent", 400, 1000)]:
        engine.add_gate(GateSpec(name=name, parent=parent, kind="range", x={"channel": "X"}, bounds=(lo, hi, None, None)), uid)
    for name, operation, operands in [("Both", "and", ["A", "B"]), ("Either", "or", ["A", "B"]), ("Not A", "not", ["A"])]:
        engine.add_gate(GateSpec(name=name, parent="Parent", kind="boolean", operation=operation, operands=operands), uid)
    engine.add_gate(GateSpec(name="Child", parent="Either", kind="range", x={"channel": "X"}, bounds=(300, 900, None, None)), uid)
    rec = engine.record(uid)
    for name, expected in [("Both", np.arange(400, 700)), ("Either", np.arange(200, 1000)),
                           ("Not A", np.r_[100:200, 700:1000]), ("Child", np.arange(300, 900))]:
        np.testing.assert_array_equal(np.flatnonzero(engine.mask(rec, name)), expected)
    (output / filename).write_bytes(buffer.getvalue())
    (output / "boolean-project.json").write_text(json.dumps(engine.project(), indent=2, ensure_ascii=False), encoding="utf-8")
    print("Synthetic only: AND 300 / OR 800 / parent-scoped NOT 400 / child 600.")
    print("Upload the FCS, open the project, then delete A and undo to restore its dependents.")
    print(output.resolve())


if __name__ == "__main__":
    main()
