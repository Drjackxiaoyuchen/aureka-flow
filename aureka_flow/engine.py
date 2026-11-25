"""FlowKit-backed analysis. Plot sampling never determines gate membership."""
from __future__ import annotations

import hashlib
import copy
import io
import json
import platform
import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import flowkit as fk
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from . import __version__
from .config import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .import_review import import_review, prepare_embedded_compensation

ROOT = Path(__file__).resolve().parents[1]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TransformSpec(StrictModel):
    kind: Literal["linear", "logicle", "asinh"] = "linear"
    t: float = Field(default=262144, gt=0, le=1e12)
    m: float = Field(default=4.5, gt=0, le=20)
    w: float = Field(default=0.5, ge=0, le=10)
    a: float = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def valid_logicle(self):
        if self.kind == "logicle" and (2 * self.w > self.m or self.a > self.m - 2 * self.w):
            raise ValueError("Logicle requires 2W ≤ M and A ≤ M − 2W.")
        return self

    def build(self):
        if self.kind == "logicle":
            return fk.transforms.LogicleTransform(self.t, self.w, self.m, self.a)
        if self.kind == "asinh":
            return fk.transforms.AsinhTransform(self.t, self.m, self.a)
        return None


class AxisSpec(StrictModel):
    channel: str = Field(min_length=1, max_length=160)
    transform: TransformSpec = Field(default_factory=TransformSpec)


class GateSpec(StrictModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^/\x00-\x1f]+$")
    parent: str = "root"
    kind: Literal["rectangle", "polygon", "range", "boolean", "ellipse"]
    x: AxisSpec | None = None
    y: AxisSpec | None = None
    compensation: Literal["raw", "fcs", "xml"] | None = "raw"
    bounds: tuple[float | None, float | None, float | None, float | None] | None = None
    vertices: list[tuple[float, float]] | None = Field(default=None, max_length=1000)
    operation: Literal["and", "or", "not"] | None = None
    operands: list[str] | None = Field(default=None, min_length=1, max_length=16)

    @model_serializer(mode="wrap")
    def serialize_gate(self, handler):
        data = handler(self)
        if self.kind != "boolean":
            # Keep schemas 1–3 readable by older Aureka versions.
            data.pop("operation", None)
            data.pop("operands", None)
        return data

    @model_validator(mode="after")
    def valid_geometry(self):
        self.name = self.name.strip()
        if not self.name or self.name == "root":
            raise ValueError("Choose a population name other than 'root'.")
        if self.kind == "boolean":
            if self.operation is None or not self.operands:
                raise ValueError("A Boolean population requires an operation and saved populations.")
            if len(set(self.operands)) != len(self.operands):
                raise ValueError("Choose each Boolean operand once.")
            if (self.operation == "not" and len(self.operands) != 1) or (self.operation != "not" and len(self.operands) < 2):
                raise ValueError("NOT requires one operand; AND/OR require at least two.")
            if any(value is not None for value in (self.x, self.y, self.bounds, self.vertices)) or self.compensation not in (None, "raw"):
                raise ValueError("Boolean populations combine saved membership; they have no independent axes, geometry or compensation.")
            self.compensation = None
            return self
        if self.operation is not None or self.operands is not None:
            raise ValueError("Only Boolean populations can have logical operations or operands.")
        if self.x is None:
            raise ValueError("A geometric gate requires an X channel.")
        if self.compensation is None:
            raise ValueError("A geometric gate requires an explicit compensation mode.")
        if self.kind != "range" and self.y is None:
            raise ValueError("A two-dimensional gate requires a Y channel.")
        if self.y and self.x.channel == self.y.channel:
            raise ValueError("Choose two different channels for a gate.")
        if self.kind in {"rectangle", "range", "ellipse"}:
            if self.bounds is None:
                raise ValueError("A rectangle or range gate requires bounds.")
            if all(value is None for value in self.bounds):
                raise ValueError("A rectangle or range gate needs at least one boundary.")
            if self.kind == "range" and (self.y is not None or self.bounds[2:] != (None, None)):
                raise ValueError("A histogram range gate has only an X channel and X boundaries.")
            for lo, hi in (self.bounds[:2], self.bounds[2:]):
                if lo is not None and hi is not None and lo >= hi:
                    raise ValueError("Each bounded axis requires min < max.")
            if self.kind == "ellipse":
                if any(value is None for value in self.bounds):
                    raise ValueError("An ellipse requires all four finite bounds.")
                radii = np.asarray([self.bounds[1]/2-self.bounds[0]/2, self.bounds[3]/2-self.bounds[2]/2])
                with np.errstate(over="ignore", under="ignore"):
                    variances = radii * radii
                if not np.isfinite(variances).all() or not (variances > 0).all():
                    raise ValueError("Ellipse bounds must give finite, positive axis radii.")
        else:
            if not self.vertices or len(set(self.vertices)) < 3:
                raise ValueError("A polygon requires at least three distinct vertices.")
            p = np.asarray(self.vertices)
            if np.linalg.matrix_rank(p - p[0]) < 2:
                raise ValueError("Polygon vertices cannot all lie on one line.")
        return self


class ViewSpec(StrictModel):
    sample_id: str
    x: AxisSpec
    y: AxisSpec | None = None
    compensation: Literal["raw", "fcs", "xml"] = "raw"
    population: str = "root"
    max_points: int = Field(default=25000, ge=100, le=50000)
    plot_type: Literal["scatter", "histogram"] = "scatter"
    histogram_bins: int = Field(default=128, ge=8, le=512)
    context_population: str | None = None

    @model_validator(mode="after")
    def valid_axes(self):
        if self.plot_type == "scatter" and self.y is None:
            raise ValueError("A scatter plot requires a Y channel.")
        return self


class GateRevisionSpec(StrictModel):
    revision: int = Field(ge=0)


class GateEditSpec(GateRevisionSpec):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^/\x00-\x1f]+$")
    bounds: tuple[float | None, float | None, float | None, float | None] | None = None
    vertices: list[tuple[float, float]] | None = Field(default=None, max_length=1000)
    operation: Literal["and", "or", "not"] | None = None
    operands: list[str] | None = Field(default=None, min_length=1, max_length=16)


class GateCopySpec(GateRevisionSpec):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^/\x00-\x1f]+$")
    parent: str = "root"
    include_children: bool = True


class ComparisonSpec(StrictModel):
    sample_ids: list[str] = Field(min_length=1, max_length=24)
    x: AxisSpec
    y: AxisSpec | None = None
    compensation: Literal["raw", "fcs", "xml"] = "raw"
    population: str = "root"
    histogram_axis: Literal["x", "y"] = "y"
    histogram_bins: int = Field(default=100, ge=8, le=512)

    @model_validator(mode="after")
    def valid_histogram_axis(self):
        if self.y is None:
            self.histogram_axis = "x"
        return self


class QuadrantsSpec(StrictModel):
    sample_id: str
    prefix: str = Field(default="YSD", min_length=1, max_length=50)
    parent: str = "root"
    x: AxisSpec
    y: AxisSpec
    compensation: Literal["raw", "fcs", "xml"] = "raw"
    expression_threshold: float
    binding_threshold: float


class ProjectSpec(StrictModel):
    format: Literal["aureka-flow-project"]
    schema_version: Literal[1, 2, 3, 4, 5]
    gates: list[GateSpec] = Field(default_factory=list, max_length=100)
    created_at: str | None = None
    software: dict = Field(default_factory=dict)
    samples: list[dict] = Field(default_factory=list)
    notes: str = ""
    workspace: dict | None = None

    @model_validator(mode="after")
    def valid_workspace(self):
        if any(g.kind == "ellipse" for g in self.gates) and self.schema_version < 5:
            raise ValueError("Ellipse populations require project schema 5.")
        if any(g.kind == "boolean" for g in self.gates) and self.schema_version < 4:
            raise ValueError("Boolean populations require project schema 4.")
        if self.workspace is not None:
            from .bd_workspace import DivaWorkspace
            w = self.workspace
            required = {"source", "worksheet", "mode", "compensation", "bindings"}
            if self.schema_version < 3 or not required.issubset(w):
                raise ValueError("A preserved XML workspace requires schema 3 or 4 and its source/settings/hash bindings.")
            if any(not isinstance(w[key], str) for key in ("worksheet", "mode", "compensation")):
                raise ValueError("XML workspace selection, mode and compensation must be strings.")
            DivaWorkspace.from_source(w["source"])
            if not isinstance(w["bindings"], dict) or len(w["bindings"]) > 2000 or any(
                not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key) or type(value) is not int
                for key, value in w["bindings"].items()
            ):
                raise ValueError("XML sample bindings require FCS SHA-256 hashes and integer sample indices.")
        return self


@dataclass
class SampleRecord:
    sample: fk.Sample
    filename: str
    digest: str
    size: int
    origin: str
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    compensation_error: str | None = None
    source_containers: list[dict] = field(default_factory=list)
    xml_compensation: fk.Matrix | None = None

    def info(self):
        s = self.sample
        return {
            "id": self.uid, "filename": self.filename, "sha256": self.digest,
            "events": s.event_count, "size_bytes": self.size, "origin": self.origin,
            "fcs_version": s.version,
            "compensation_available": s.compensation is not None,
            "compensation_error": self.compensation_error,
            "source_containers": list(self.source_containers),
            "xml_compensation_available": self.xml_compensation is not None,
            "import_review": import_review(s, self.compensation_error),
            "channels": [
                {"id": n, "label": f"{n} · {p}" if p else n,
                 "stain": p, "parameter_number": i + 1, "fluorescence": i in s.fluoro_indices}
                for i, (n, p) in enumerate(zip(s.pnn_labels, s.pns_labels))
            ],
        }


def finite_number(value):
    return float(value) if np.isfinite(value) else None


class AnalysisEngine:
    GATE_HISTORY_STEPS = 20
    GATE_HISTORY_BYTES = 2 * 1024**2

    def __init__(self):
        self.samples: dict[str, SampleRecord] = {}
        self.gates: list[GateSpec] = []
        self.revision = 0
        self.lock = threading.RLock()
        self._results = OrderedDict()
        self.workspace = None
        # Definitions only: never retain event arrays, result masks or source XML in history.
        self._gate_undo: list[bytes] = []
        self._gate_redo: list[bytes] = []

    def load(self, data: bytes, filename: str, origin="uploaded FCS"):
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"Each FCS file must be {MAX_FILE_BYTES // 1024**2} MB or smaller.")
        digest = hashlib.sha256(data).hexdigest()
        for rec in self.samples.values():
            if rec.digest == digest:
                return rec.info()
        if len(self.samples) >= 24 or sum(r.size for r in self.samples.values()) + len(data) > MAX_TOTAL_BYTES:
            raise ValueError(f"Workspace limit: 24 samples / {MAX_TOTAL_BYTES // 1024**2} MB of FCS files. Remove samples before adding more.")
        filename = Path(filename.replace("\\", "/")).name
        s = fk.Sample(io.BytesIO(data), sample_id=digest, subsample=1000)
        if not s.event_count:
            raise ValueError("The FCS file contains no events.")
        if len(set(s.pnn_labels)) != len(s.pnn_labels):
            raise ValueError("Duplicate detector names are ambiguous. Rename channels before import.")
        rec = SampleRecord(s, filename, digest, len(data), origin)
        rec.compensation_error = prepare_embedded_compensation(s)
        if self.workspace and digest in self.workspace["bindings"] and self.workspace["mode"] == "reconstructed":
            from .bd_workspace import DivaWorkspace
            if self.workspace["compensation"] == "xml":
                rec.xml_compensation = DivaWorkspace.from_source(self.workspace["source"]).matrix(self.workspace["bindings"][digest])
                if not set(rec.xml_compensation.detectors).issubset(s.pnn_labels):
                    raise ValueError("Restored XML compensation detectors do not match this FCS file.")
        self.samples[rec.uid] = rec
        return rec.info()

    def record(self, uid):
        if uid not in self.samples:
            raise ValueError("Sample is no longer loaded. Upload it again.")
        return self.samples[uid]

    def remove_sample(self, uid):
        self.record(uid)
        del self.samples[uid]
        self._results.clear()

    def events(self, rec, compensation):
        if compensation == "xml":
            if rec.xml_compensation is None:
                raise ValueError("No reviewed XML compensation is bound to this FCS hash. Import its XML and matching FCS first.")
            return rec.xml_compensation.apply(rec.sample)  # always source values, never FCS-compensated values
        if compensation == "fcs" and rec.sample.compensation is None:
            detail = f" {rec.compensation_error}" if rec.compensation_error else ""
            raise ValueError("No usable embedded spillover matrix in this sample." + detail +
                             " Use source values without additional compensation, or re-export a compatible matrix.")
        return rec.sample.get_events(source="comp" if compensation == "fcs" else "raw")

    def axis(self, rec, axis, compensation):
        if axis.channel not in rec.sample.pnn_labels:
            raise ValueError(f"Channel '{axis.channel}' is missing from {rec.filename}.")
        values = self.events(rec, compensation)[:, rec.sample.get_channel_index(axis.channel)]
        transform = axis.transform.build()
        return transform.apply(values.copy()) if transform else values

    def strategy(self, gates=None, rec=None):
        gates = self.gates if gates is None else gates
        strategy = fk.GatingStrategy()
        if rec is not None and rec.xml_compensation is not None:
            strategy.add_comp_matrix("XML", rec.xml_compensation)
        paths = {"root": ("root",)}
        by_name = {}
        for i, spec in enumerate(gates):
            if spec.name in paths:
                raise ValueError(f"Duplicate population name: {spec.name}.")
            if spec.parent not in paths:
                raise ValueError(f"Parent '{spec.parent}' must appear before its children.")
            if spec.kind == "boolean":
                if any(ref not in by_name for ref in spec.operands):
                    raise ValueError("Boolean operands must be saved populations appearing earlier; forward, missing and cyclic references are not allowed.")
                if any(by_name[ref].parent != spec.parent for ref in spec.operands):
                    raise ValueError("Boolean operands must share the Boolean population's parent.")
                gate = fk.gates.BooleanGate(spec.name, spec.operation, [
                    {"ref": ref, "path": paths[ref][:-1], "complement": False} for ref in spec.operands])
                strategy.add_gate(gate, paths[spec.parent])
                paths[spec.name] = paths[spec.parent] + (spec.name,)
                by_name[spec.name] = spec
                continue
            dims = []
            for j, axis in enumerate((spec.x, spec.y)):
                if axis is None:
                    continue
                transform_id = None
                transform = axis.transform.build()
                if transform:
                    transform_id = f"transform_{i}_{j}"
                    strategy.add_transform(transform_id, transform)
                limits = (None, None)
                if spec.kind in {"rectangle", "range"}:
                    limits = spec.bounds[:2] if j == 0 else spec.bounds[2:]
                    if limits == (None, None):
                        continue  # an unbounded axis is omitted from this range gate
                dims.append(fk.Dimension(
                    axis.channel, compensation_ref={"fcs": "FCS", "xml": "XML", "raw": "uncompensated"}[spec.compensation],
                    transformation_ref=transform_id, range_min=limits[0], range_max=limits[1],
                ))
            if spec.kind == "ellipse":
                lo, hi, bottom, top = spec.bounds
                center = [lo/2+hi/2, bottom/2+top/2]
                covariance = np.diag([(hi/2-lo/2)**2, (top/2-bottom/2)**2]).tolist()
                gate = fk.gates.EllipsoidGate(spec.name, dims, center, covariance, 1.)
            else:
                gate = (fk.gates.RectangleGate(spec.name, dims) if spec.kind in {"rectangle", "range"}
                        else fk.gates.PolygonGate(spec.name, dims, spec.vertices))
            strategy.add_gate(gate, paths[spec.parent])
            paths[spec.name] = paths[spec.parent] + (spec.name,)
            by_name[spec.name] = spec
        return strategy

    def validate_sample(self, rec, gates=None):
        if self.workspace and self.workspace["mode"] == "reconstructed" and rec.digest not in self.workspace["bindings"]:
            raise ValueError("This FCS hash is not bound to the imported XML. Review a fresh XML import before applying its gates.")
        for spec in self.gates if gates is None else gates:
            if spec.kind == "boolean":
                continue  # referenced gates retain their own transforms/compensation
            for axis in (spec.x, spec.y):
                if axis is None:
                    continue
                if axis.channel not in rec.sample.pnn_labels:
                    raise ValueError(f"Gate '{spec.name}' needs missing channel '{axis.channel}'.")
            self.events(rec, spec.compensation)

    def results(self, rec):
        key = (rec.uid, self.revision)
        if key not in self._results:
            self.validate_sample(rec)
            self._results[key] = self.strategy(rec=rec).gate_sample(rec.sample) if self.gates else None
            while len(self._results) > 8:
                self._results.popitem(last=False)
        self._results.move_to_end(key)
        return self._results[key]

    def mask(self, rec, population):
        if population == "root":
            return np.ones(rec.sample.event_count, dtype=bool)
        if population not in {g.name for g in self.gates}:
            raise ValueError(f"Population '{population}' does not exist.")
        return self.results(rec).get_gate_membership(population)

    @staticmethod
    def _gate_snapshot(gates):
        return json.dumps([g.model_dump() for g in gates], ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")

    def gate_history(self):
        return {"revision": self.revision, "undo": len(self._gate_undo), "redo": len(self._gate_redo),
                "max_steps": self.GATE_HISTORY_STEPS, "max_bytes": self.GATE_HISTORY_BYTES}

    def _trim_gate_history(self):
        while (len(self._gate_undo) + len(self._gate_redo) > self.GATE_HISTORY_STEPS or
               sum(map(len, self._gate_undo)) + sum(map(len, self._gate_redo)) > self.GATE_HISTORY_BYTES):
            # Discard the most distant undo first, then the most distant redo.
            (self._gate_undo if self._gate_undo else self._gate_redo).pop(0)

    def _check_gate_revision(self, revision):
        if revision != self.revision:
            raise ValueError("The gate strategy changed in another request. Refresh before editing or undoing.")

    def set_gates(self, gates, *, remember=False):
        self.strategy(gates)  # validate structure before mutation
        if remember:
            if [g.model_dump() for g in gates] == [g.model_dump() for g in self.gates]:
                return
            self._gate_undo.append(self._gate_snapshot(self.gates))
            self._gate_redo.clear()
            self._trim_gate_history()
        else:
            # Source/compensation replacements and project/session resets are history barriers.
            self._gate_undo.clear()
            self._gate_redo.clear()
        self.gates = copy.deepcopy(gates)
        self.revision += 1
        self._results.clear()

    def edit_gate(self, name, edit, uid):
        self._check_gate_revision(edit.revision)
        original = next((g for g in self.gates if g.name == name), None)
        if original is None:
            raise ValueError("Population does not exist.")
        if original.kind == "polygon" and edit.bounds is not None:
            raise ValueError("A polygon edit requires vertices, not bounds.")
        if original.kind != "polygon" and edit.vertices is not None:
            raise ValueError("A rectangle or range edit requires bounds, not vertices.")
        replacement = GateSpec.model_validate(original.model_dump() | edit.model_dump(exclude={"revision"}, exclude_unset=True))
        proposed = []
        for gate in self.gates:
            changed = replacement if gate.name == name else gate
            updates = {}
            if changed.parent == name:
                updates["parent"] = replacement.name
            if changed.kind == "boolean":
                updates["operands"] = [replacement.name if ref == name else ref for ref in changed.operands]
            proposed.append(changed.model_copy(update=updates))
        rec = self.record(uid)
        strategy = self.strategy(proposed, rec)
        self.validate_sample(rec, proposed)
        result = strategy.gate_sample(rec.sample)  # entire tree validated before committing any edit
        count = int(result.get_gate_count(replacement.name))
        self.set_gates(proposed, remember=True)
        return {"name": replacement.name, "count": count}

    def navigate_gate_history(self, direction, revision):
        self._check_gate_revision(revision)
        if direction not in {"undo", "redo"}:
            raise ValueError("Choose undo or redo.")
        source, destination = ((self._gate_undo, self._gate_redo) if direction == "undo" else
                               (self._gate_redo, self._gate_undo))
        if not source:
            raise ValueError(f"No gate change to {direction}.")
        gates = [GateSpec.model_validate(g) for g in json.loads(source[-1])]
        self.strategy(gates)
        destination.append(self._gate_snapshot(self.gates))
        source.pop()
        self._trim_gate_history()
        self.gates = gates
        self.revision += 1
        self._results.clear()  # every sample and descendant must be recalculated on next read
        return self.gate_history()

    def add_gate(self, spec, uid):
        if len(self.gates) >= 100:
            raise ValueError("Workspace limit: 100 gates.")
        rec = self.record(uid)
        proposed = self.gates + [spec]
        strategy = self.strategy(proposed, rec)
        self.validate_sample(rec, proposed)
        result = strategy.gate_sample(rec.sample)
        count = int(result.get_gate_count(spec.name))
        self.set_gates(proposed, remember=True)
        return {"name": spec.name, "count": count}

    def delete_gate(self, name):
        if name not in {g.name for g in self.gates}:
            raise ValueError("Population does not exist.")
        deleted = {name}
        for spec in self.gates:
            if spec.parent in deleted or any(ref in deleted for ref in spec.operands or []):
                deleted.add(spec.name)
        self.set_gates([g for g in self.gates if g.name not in deleted], remember=True)
        return sorted(deleted)

    def copy_gate(self, name, spec, uid):
        self._check_gate_revision(spec.revision)
        source = next((g for g in self.gates if g.name == name), None)
        if source is None:
            raise ValueError("Population does not exist.")
        selected = {name}
        if spec.include_children:
            for gate in self.gates:
                if gate.parent in selected:
                    selected.add(gate.name)
        if len(self.gates) + len(selected) > 100:
            raise ValueError("Copy would exceed the workspace limit of 100 gates.")
        used = {g.name for g in self.gates}
        root_name = spec.name.strip()
        if root_name in used:
            raise ValueError("Choose a new name for the copied population.")
        names = {name: root_name}
        used.add(root_name)
        for gate in self.gates:
            if gate.name not in selected or gate.name == name:
                continue
            n = 1
            while True:
                suffix = " copy" if n == 1 else f" copy {n}"
                candidate = gate.name[:80-len(suffix)] + suffix
                if candidate not in used:
                    break
                n += 1
            names[gate.name] = candidate
            used.add(candidate)
        copies = []
        for gate in self.gates:
            if gate.name not in selected:
                continue
            data = gate.model_dump() | {"name": names[gate.name],
                "parent": spec.parent if gate.name == name else names[gate.parent]}
            if gate.operands:
                data["operands"] = [names.get(ref, ref) for ref in gate.operands]
            copies.append(GateSpec.model_validate(data))
        proposed = self.gates + copies
        rec = self.record(uid)
        strategy = self.strategy(proposed, rec)
        self.validate_sample(rec, proposed)
        results = strategy.gate_sample(rec.sample)
        self.set_gates(proposed, remember=True)
        return {"name": root_name, "copied": [g.name for g in copies], "name_mapping": names,
                "count": int(results.get_gate_count(root_name))}

    def add_quadrants(self, spec):
        rec = self.record(spec.sample_id)
        e, b = spec.expression_threshold, spec.binding_threshold
        definitions = [
            ("E− B−", [None, e, None, b]), ("E+ B−", [e, None, None, b]),
            ("E− B+", [None, e, b, None]), ("E+ B+", [e, None, b, None]),
        ]
        added = [GateSpec(name=f"{spec.prefix} {name}", parent=spec.parent, kind="rectangle",
                          x=spec.x, y=spec.y, compensation=spec.compensation, bounds=bounds)
                 for name, bounds in definitions]
        added.append(GateSpec(name=f"{spec.prefix} Expression+", parent=spec.parent, kind="rectangle",
                              x=spec.x, y=spec.y, compensation=spec.compensation, bounds=[e, None, None, None]))
        proposed = self.gates + added
        if len(proposed) > 100:
            raise ValueError("Workspace limit: 100 gates.")
        strategy = self.strategy(proposed, rec)
        self.validate_sample(rec, proposed)
        result = strategy.gate_sample(rec.sample)
        self.set_gates(proposed, remember=True)
        return {"populations": [{"name": g.name, "count": int(result.get_gate_count(g.name))} for g in added]}

    def populations(self, rec):
        result = self.results(rec)
        rows = [{"name": "root", "label": "All events", "parent": None, "count": rec.sample.event_count,
                 "percent_total": 100.0, "percent_parent": 100.0, "depth": 0}]
        depths = {"root": 0}
        for g in self.gates:
            depths[g.name] = depths[g.parent] + 1
            rows.append({
                "name": g.name, "label": g.name, "parent": g.parent,
                "count": int(result.get_gate_count(g.name)),
                "percent_total": float(result.get_gate_absolute_percent(g.name)),
                "percent_parent": float(result.get_gate_relative_percent(g.name)), "depth": depths[g.name],
            })
        return rows

    def view(self, spec):
        rec = self.record(spec.sample_id)
        # Even at root, incompatible strategies are surfaced to the operator.
        populations = self.populations(rec)
        mask = self.mask(rec, spec.population)
        context_mask = None
        if spec.context_population is not None:
            ancestors, parent = set(), spec.population
            by_name = {g.name: g for g in self.gates}
            while parent != "root":
                parent = by_name[parent].parent
                ancestors.add(parent)
            if spec.context_population not in ancestors:
                raise ValueError("Backgating context must be a strict ancestor of the selected population.")
            context_mask = self.mask(rec, spec.context_population)
        x = self.axis(rec, spec.x, spec.compensation)
        if spec.plot_type == "histogram":
            finite = np.isfinite(x)
            values = x[mask & finite]
            context_values = x[context_mask & finite] if context_mask is not None else values
            if len(context_values):
                lo, hi = float(context_values.min()), float(context_values.max())
                if lo == hi:
                    lo, hi = lo - .5, hi + .5
            else:
                lo, hi = 0., 1.
            edges = np.linspace(lo, hi, spec.histogram_bins + 1)
            counts, _ = np.histogram(values, bins=edges)
            denominator = len(context_values)
            view = {
                "sample": rec.info(), "populations": populations, "population": spec.population,
                "plot_type": "histogram", "total_count": rec.sample.event_count,
                "population_count": int(mask.sum()), "display_count": len(values),
                "nonfinite_count": int((mask & ~finite).sum()),
                "median_x": finite_number(np.median(values)) if len(values) else None, "median_y": None,
                "histogram": {"edges": edges.tolist(), "centers": ((edges[:-1]+edges[1:])/2).tolist(),
                              "widths": np.diff(edges).tolist(), "counts": counts.tolist(),
                              "percent": (counts*100/denominator).tolist() if denominator else [0.]*spec.histogram_bins,
                              "finite_count": len(values), "normalization_count": denominator},
            }
            if context_mask is not None:
                context_counts, _ = np.histogram(context_values, bins=edges)
                view["context"] = {"population": spec.context_population, "population_count": int(context_mask.sum()),
                    "display_count": len(context_values), "nonfinite_count": int((context_mask & ~finite).sum()),
                    "histogram": {"counts": context_counts.tolist(), "percent": (context_counts*100/denominator).tolist()
                                  if denominator else [0.]*spec.histogram_bins}}
            return view
        y = self.axis(rec, spec.y, spec.compensation)
        finite = np.isfinite(x) & np.isfinite(y)
        indices = np.flatnonzero(mask & finite)
        if len(indices) > spec.max_points:
            indices = np.sort(np.random.default_rng(17).choice(indices, spec.max_points, replace=False))
        selected_x, selected_y = x[mask & np.isfinite(x)], y[mask & np.isfinite(y)]
        view = {
            "sample": rec.info(), "populations": populations, "population": spec.population,
            "total_count": rec.sample.event_count, "population_count": int(mask.sum()),
            "display_count": len(indices), "nonfinite_count": int((mask & ~finite).sum()),
            "x": x[indices].tolist(), "y": y[indices].tolist(), "event_indices": indices.tolist(),
            "median_x": finite_number(np.median(selected_x)) if len(selected_x) else None,
            "median_y": finite_number(np.median(selected_y)) if len(selected_y) else None,
        }
        if context_mask is not None:
            context_indices = np.flatnonzero(context_mask & finite)
            if len(context_indices) > spec.max_points:
                context_indices = np.sort(np.random.default_rng(19).choice(context_indices, spec.max_points, replace=False))
            view["context"] = {"population": spec.context_population, "population_count": int(context_mask.sum()),
                "display_count": len(context_indices), "nonfinite_count": int((context_mask & ~finite).sum()),
                "x": x[context_indices].tolist(), "y": y[context_indices].tolist(), "event_indices": context_indices.tolist()}
        return view

    def compare(self, spec):
        rows, distributions, all_x = [], [], []
        for uid in spec.sample_ids:
            rec = self.record(uid)
            row = {"sample": rec.filename, "sample_id": uid, "sha256": rec.digest,
                   "origin": rec.origin, "population": spec.population,
                   "compensation": spec.compensation, "x_channel": spec.x.channel,
                   "x_transform": json.dumps(spec.x.transform.model_dump(), sort_keys=True),
                   "y_channel": spec.y.channel if spec.y else None,
                   "y_transform": json.dumps(spec.y.transform.model_dump(), sort_keys=True) if spec.y else None}
            try:
                mask = self.mask(rec, spec.population)
                # A root comparison still validates every applied gate for transparency.
                self.results(rec)
                x = self.axis(rec, spec.x, spec.compensation)[mask]
                y = self.axis(rec, spec.y, spec.compensation)[mask] if spec.y else np.array([])
                xf, yf = x[np.isfinite(x)], y[np.isfinite(y)]
                count = int(mask.sum())
                gate = next((g for g in self.gates if g.name == spec.population), None)
                parent_count = int(self.mask(rec, gate.parent).sum()) if gate else rec.sample.event_count
                row.update(count=count, total_events=rec.sample.event_count,
                           percent_total=100 * count / rec.sample.event_count,
                           percent_parent=100 * count / parent_count if parent_count else 0.0,
                           median_x=finite_number(np.median(xf)) if len(xf) else None,
                           median_y=finite_number(np.median(yf)) if len(yf) else None,
                           nonfinite_x=int((~np.isfinite(x)).sum()), nonfinite_y=int((~np.isfinite(y)).sum()), error="")
                histogram_values = xf if spec.histogram_axis == "x" else yf
                distributions.append((uid, rec.filename, histogram_values))
                if len(histogram_values):
                    all_x.append((float(histogram_values.min()), float(histogram_values.max())))
            except (ValueError, KeyError) as exc:
                row["error"] = str(exc)
            rows.append(row)
        histogram = []
        if all_x:
            lo, hi = min(x[0] for x in all_x), max(x[1] for x in all_x)
            if lo == hi:
                lo, hi = lo - .5, hi + .5
            edges = np.linspace(lo, hi, spec.histogram_bins + 1)
            centers = ((edges[:-1] + edges[1:]) / 2).tolist()
            for uid, label, values in distributions:
                counts, _ = np.histogram(values, bins=edges)
                histogram.append({"sample_id": uid, "sample": label, "x": centers,
                                  "counts": counts.tolist(), "finite_count": len(values),
                                  "percent": (counts * 100 / len(values)).tolist() if len(values) else [0.] * spec.histogram_bins,
                                  "modal": (counts * 100 / counts.max()).tolist() if counts.max() else [0.] * spec.histogram_bins})
        return {"rows": rows, "histograms": histogram}

    def population_table(self, spec):
        """All samples × all populations, retaining paths, denominators and source provenance."""
        rows = []
        for uid in spec.sample_ids:
            rec = self.record(uid)
            base = {"sample": rec.filename, "sample_id": uid, "sha256": rec.digest, "origin": rec.origin,
                    "compensation": spec.compensation, "x_channel": spec.x.channel,
                    "x_transform": json.dumps(spec.x.transform.model_dump(), sort_keys=True),
                    "y_channel": spec.y.channel if spec.y else None,
                    "y_transform": json.dumps(spec.y.transform.model_dump(), sort_keys=True) if spec.y else None}
            try:
                populations = self.populations(rec)
                x = self.axis(rec, spec.x, spec.compensation)
                y = self.axis(rec, spec.y, spec.compensation) if spec.y else None
                paths = {"root": "All events"}
                for population in populations:
                    name, parent = population["name"], population["parent"]
                    if parent:
                        paths[name] = paths[parent] + " / " + name
                    mask = self.mask(rec, name)
                    xf = x[mask & np.isfinite(x)]
                    yf = y[mask & np.isfinite(y)] if y is not None else np.array([])
                    rows.append({**base, "population": name, "parent": parent, "path": paths[name],
                        "count": population["count"], "total_events": rec.sample.event_count,
                        "percent_total": population["percent_total"], "percent_parent": population["percent_parent"],
                        "median_x": finite_number(np.median(xf)) if len(xf) else None,
                        "median_y": finite_number(np.median(yf)) if len(yf) else None,
                        "nonfinite_x": int(mask.sum())-len(xf),
                        "nonfinite_y": int(mask.sum())-len(yf) if y is not None else 0, "error": ""})
            except (ValueError, KeyError) as exc:
                rows.append({**base, "population": None, "parent": None, "path": "", "error": str(exc)})
        return {"rows": rows}

    def project(self):
        return {
            "format": "aureka-flow-project", "schema_version": 5 if any(g.kind == "ellipse" for g in self.gates) else 4 if any(g.kind == "boolean" for g in self.gates) else 3 if self.workspace else 2 if any(g.kind == "range" for g in self.gates) else 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "software": {"aureka_flow": __version__, "flowkit": fk.__version__, "python": platform.python_version()},
            "samples": [{**rec.info(), "fcs_metadata": rec.sample.get_metadata()} for rec in self.samples.values()],
            "gates": [g.model_dump() for g in self.gates],
            **({"workspace": copy.deepcopy(self.workspace)} if self.workspace else {}),
            "notes": "FCS event data are not embedded. Re-upload matching source files; SHA-256 identifies each source. "
                     "Gate coordinates retain their individual transforms and compensation modes. "
                     "Root means all parsed events; no automatic QC, singlet, or viability gates are applied. "
                     "FlowKit raw events include standard FCS gain/log/time preprocessing. "
                     "Fluorescence is assay-specific; no affinity or functional potency is inferred.",
        }

    def import_workspace(self, doc, worksheet, mode, compensation, acknowledged=False):
        from .bd_workspace import prepare_import
        if mode == "reconstructed" and not self.samples:
            raise ValueError("Load matching FCS files before reconstructing XML gates.")
        workspace, gates, matrices = prepare_import(self, doc, worksheet, mode, compensation, acknowledged)
        self.workspace = workspace
        for uid, rec in self.samples.items():
            rec.xml_compensation = matrices.get(uid)
        self.set_gates(gates)

    def restore_project(self, project):
        if project.workspace:
            from .bd_workspace import DivaWorkspace, prepare_import
            saved = project.workspace
            doc = DivaWorkspace.from_source(saved["source"])
            workspace, _, matrices = prepare_import(self, doc, saved["worksheet"], saved["mode"],
                                                    saved["compensation"], True, saved["bindings"])
        else:
            workspace, matrices = None, {}
            if any(g.compensation == "xml" for g in project.gates):
                raise ValueError("XML-compensated gates require their preserved workspace source and hash bindings.")
        self.strategy(project.gates)
        self.workspace = workspace
        for uid, rec in self.samples.items():
            rec.xml_compensation = matrices.get(uid)
        self.set_gates(project.gates)

    def gatingml(self, rec=None):
        """Use XML-safe IDs and retain human labels in a comment and project JSON."""
        if not self.gates:
            raise ValueError("Save at least one population before exporting GatingML.")
        from lxml import etree
        mapping = {}
        for i, gate in enumerate(self.gates):
            slug = re.sub(r"[^A-Za-z0-9_]+", "_", gate.name).strip("_")[:50]
            mapping[gate.name] = f"g{i + 1:03d}_{slug or 'population'}"
        exported = [g.model_copy(update={"name": mapping[g.name], "parent": mapping.get(g.parent, "root"),
                                         "operands": [mapping[ref] for ref in g.operands] if g.operands else None})
                    for g in self.gates]
        buffer = io.BytesIO()
        if any(g.compensation == "xml" for g in exported) and (rec is None or rec.xml_compensation is None):
            raise ValueError("Choose a hash-matched sample to export its XML compensation with GatingML.")
        fk.export_gatingml(self.strategy(exported, rec), buffer)
        root = etree.fromstring(buffer.getvalue())
        labels = " Aureka population label to XML identifier:\n" + json.dumps(mapping, ensure_ascii=False, indent=2) + " "
        root.insert(0, etree.Comment(labels.replace("--", "- -")))
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True), mapping
