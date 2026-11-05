"""FlowKit-backed analysis. Plot sampling never determines gate membership."""
from __future__ import annotations

import hashlib
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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import __version__

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024


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
    kind: Literal["rectangle", "polygon"]
    x: AxisSpec
    y: AxisSpec
    compensation: Literal["raw", "fcs"] = "raw"
    bounds: tuple[float | None, float | None, float | None, float | None] | None = None
    vertices: list[tuple[float, float]] | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def valid_geometry(self):
        self.name = self.name.strip()
        if not self.name or self.name == "root":
            raise ValueError("Choose a population name other than 'root'.")
        if self.x.channel == self.y.channel:
            raise ValueError("Choose two different channels for a gate.")
        if self.kind == "rectangle":
            if self.bounds is None:
                raise ValueError("A rectangle requires bounds.")
            if all(value is None for value in self.bounds):
                raise ValueError("A rectangle needs at least one boundary.")
            for lo, hi in (self.bounds[:2], self.bounds[2:]):
                if lo is not None and hi is not None and lo >= hi:
                    raise ValueError("A rectangle requires X min < X max and Y min < Y max.")
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
    y: AxisSpec
    compensation: Literal["raw", "fcs"] = "raw"
    population: str = "root"
    max_points: int = Field(default=25000, ge=100, le=50000)


class ComparisonSpec(StrictModel):
    sample_ids: list[str] = Field(min_length=1, max_length=24)
    x: AxisSpec
    y: AxisSpec
    compensation: Literal["raw", "fcs"] = "raw"
    population: str = "root"
    histogram_axis: Literal["x", "y"] = "y"


class QuadrantsSpec(StrictModel):
    sample_id: str
    prefix: str = Field(default="YSD", min_length=1, max_length=50)
    parent: str = "root"
    x: AxisSpec
    y: AxisSpec
    compensation: Literal["raw", "fcs"] = "raw"
    expression_threshold: float
    binding_threshold: float


class ProjectSpec(StrictModel):
    format: Literal["aureka-flow-project"]
    schema_version: Literal[1]
    gates: list[GateSpec] = Field(default_factory=list, max_length=100)
    created_at: str | None = None
    software: dict = Field(default_factory=dict)
    samples: list[dict] = Field(default_factory=list)
    notes: str = ""


@dataclass
class SampleRecord:
    sample: fk.Sample
    filename: str
    digest: str
    size: int
    origin: str
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    compensation_error: str | None = None

    def info(self):
        s = self.sample
        return {
            "id": self.uid, "filename": self.filename, "sha256": self.digest,
            "events": s.event_count, "size_bytes": self.size, "origin": self.origin,
            "fcs_version": s.version,
            "compensation_available": s.compensation is not None,
            "compensation_error": self.compensation_error,
            "channels": [
                {"id": n, "label": f"{n} · {p}" if p else n,
                 "stain": p, "fluorescence": i in s.fluoro_indices}
                for i, (n, p) in enumerate(zip(s.pnn_labels, s.pns_labels))
            ],
        }


def finite_number(value):
    return float(value) if np.isfinite(value) else None


class AnalysisEngine:
    def __init__(self):
        self.samples: dict[str, SampleRecord] = {}
        self.gates: list[GateSpec] = []
        self.revision = 0
        self.lock = threading.RLock()
        self._results = OrderedDict()

    def load(self, data: bytes, filename: str, origin="uploaded FCS"):
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("Each FCS file must be 100 MB or smaller.")
        digest = hashlib.sha256(data).hexdigest()
        for rec in self.samples.values():
            if rec.digest == digest:
                return rec.info()
        if len(self.samples) >= 24 or sum(r.size for r in self.samples.values()) + len(data) > MAX_TOTAL_BYTES:
            raise ValueError("Workspace limit: 24 samples / 300 MB of FCS files. Remove samples before adding more.")
        filename = Path(filename.replace("\\", "/")).name
        s = fk.Sample(io.BytesIO(data), sample_id=digest, subsample=1000)
        if not s.event_count:
            raise ValueError("The FCS file contains no events.")
        if len(set(s.pnn_labels)) != len(s.pnn_labels):
            raise ValueError("Duplicate detector names are ambiguous. Rename channels before import.")
        rec = SampleRecord(s, filename, digest, len(data), origin)
        spill = s.metadata.get("spillover") or s.metadata.get("spill")
        if spill:
            try:
                s.apply_compensation(spill)
            except Exception as exc:
                rec.compensation_error = str(exc)
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
        if compensation == "fcs" and rec.sample.compensation is None:
            raise ValueError("No usable embedded spillover matrix in this sample. Choose uncompensated data.")
        return rec.sample.get_events(source="comp" if compensation == "fcs" else "raw")

    def axis(self, rec, axis, compensation):
        if axis.channel not in rec.sample.pnn_labels:
            raise ValueError(f"Channel '{axis.channel}' is missing from {rec.filename}.")
        values = self.events(rec, compensation)[:, rec.sample.get_channel_index(axis.channel)]
        transform = axis.transform.build()
        return transform.apply(values.copy()) if transform else values

    def strategy(self, gates=None):
        gates = self.gates if gates is None else gates
        strategy = fk.GatingStrategy()
        paths = {"root": ("root",)}
        for i, spec in enumerate(gates):
            if spec.name in paths:
                raise ValueError(f"Duplicate population name: {spec.name}.")
            if spec.parent not in paths:
                raise ValueError(f"Parent '{spec.parent}' must appear before its children.")
            dims = []
            for j, axis in enumerate((spec.x, spec.y)):
                transform_id = None
                transform = axis.transform.build()
                if transform:
                    transform_id = f"transform_{i}_{j}"
                    strategy.add_transform(transform_id, transform)
                limits = (None, None)
                if spec.kind == "rectangle":
                    limits = spec.bounds[:2] if j == 0 else spec.bounds[2:]
                    if limits == (None, None):
                        continue  # an unbounded axis is omitted from this range gate
                dims.append(fk.Dimension(
                    axis.channel, compensation_ref="FCS" if spec.compensation == "fcs" else "uncompensated",
                    transformation_ref=transform_id, range_min=limits[0], range_max=limits[1],
                ))
            gate = (fk.gates.RectangleGate(spec.name, dims) if spec.kind == "rectangle"
                    else fk.gates.PolygonGate(spec.name, dims, spec.vertices))
            strategy.add_gate(gate, paths[spec.parent])
            paths[spec.name] = paths[spec.parent] + (spec.name,)
        return strategy

    def validate_sample(self, rec, gates=None):
        for spec in self.gates if gates is None else gates:
            for axis in (spec.x, spec.y):
                if axis.channel not in rec.sample.pnn_labels:
                    raise ValueError(f"Gate '{spec.name}' needs missing channel '{axis.channel}'.")
            self.events(rec, spec.compensation)

    def results(self, rec):
        key = (rec.uid, self.revision)
        if key not in self._results:
            self.validate_sample(rec)
            self._results[key] = self.strategy().gate_sample(rec.sample) if self.gates else None
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

    def set_gates(self, gates):
        self.strategy(gates)  # validate structure before mutation
        self.gates = gates
        self.revision += 1
        self._results.clear()

    def add_gate(self, spec, uid):
        if len(self.gates) >= 100:
            raise ValueError("Workspace limit: 100 gates.")
        rec = self.record(uid)
        proposed = self.gates + [spec]
        strategy = self.strategy(proposed)
        self.validate_sample(rec, proposed)
        result = strategy.gate_sample(rec.sample)
        count = int(result.get_gate_count(spec.name))
        self.set_gates(proposed)
        return {"name": spec.name, "count": count}

    def delete_gate(self, name):
        if name not in {g.name for g in self.gates}:
            raise ValueError("Population does not exist.")
        deleted = {name}
        for spec in self.gates:
            if spec.parent in deleted:
                deleted.add(spec.name)
        self.set_gates([g for g in self.gates if g.name not in deleted])
        return sorted(deleted)

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
        strategy = self.strategy(proposed)
        self.validate_sample(rec, proposed)
        result = strategy.gate_sample(rec.sample)
        self.set_gates(proposed)
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
        x = self.axis(rec, spec.x, spec.compensation)
        y = self.axis(rec, spec.y, spec.compensation)
        finite = np.isfinite(x) & np.isfinite(y)
        indices = np.flatnonzero(mask & finite)
        if len(indices) > spec.max_points:
            indices = np.sort(np.random.default_rng(17).choice(indices, spec.max_points, replace=False))
        selected_x, selected_y = x[mask & np.isfinite(x)], y[mask & np.isfinite(y)]
        return {
            "sample": rec.info(), "populations": populations, "population": spec.population,
            "total_count": rec.sample.event_count, "population_count": int(mask.sum()),
            "display_count": len(indices), "nonfinite_count": int((mask & ~finite).sum()),
            "x": x[indices].tolist(), "y": y[indices].tolist(), "event_indices": indices.tolist(),
            "median_x": finite_number(np.median(selected_x)) if len(selected_x) else None,
            "median_y": finite_number(np.median(selected_y)) if len(selected_y) else None,
        }

    def compare(self, spec):
        rows, distributions, all_x = [], [], []
        for uid in spec.sample_ids:
            rec = self.record(uid)
            row = {"sample": rec.filename, "sample_id": uid, "sha256": rec.digest,
                   "origin": rec.origin, "population": spec.population,
                   "compensation": spec.compensation, "x_channel": spec.x.channel,
                   "x_transform": json.dumps(spec.x.transform.model_dump(), sort_keys=True),
                   "y_channel": spec.y.channel,
                   "y_transform": json.dumps(spec.y.transform.model_dump(), sort_keys=True)}
            try:
                mask = self.mask(rec, spec.population)
                # A root comparison still validates every applied gate for transparency.
                self.results(rec)
                x = self.axis(rec, spec.x, spec.compensation)[mask]
                y = self.axis(rec, spec.y, spec.compensation)[mask]
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
            edges = np.linspace(lo, hi, 101)
            centers = ((edges[:-1] + edges[1:]) / 2).tolist()
            for uid, label, values in distributions:
                counts, _ = np.histogram(values, bins=edges)
                histogram.append({"sample_id": uid, "sample": label, "x": centers,
                                  "percent": (counts * 100 / len(values)).tolist() if len(values) else [0.] * 100})
        return {"rows": rows, "histograms": histogram}

    def project(self):
        return {
            "format": "aureka-flow-project", "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "software": {"aureka_flow": __version__, "flowkit": fk.__version__, "python": platform.python_version()},
            "samples": [{**rec.info(), "fcs_metadata": rec.sample.get_metadata()} for rec in self.samples.values()],
            "gates": [g.model_dump() for g in self.gates],
            "notes": "FCS event data are not embedded. Re-upload matching source files; SHA-256 identifies each source. "
                     "Gate coordinates retain their individual transforms and compensation modes. "
                     "Root means all parsed events; no automatic QC, singlet, or viability gates are applied. "
                     "FlowKit raw events include standard FCS gain/log/time preprocessing. "
                     "Fluorescence is assay-specific; no affinity or functional potency is inferred.",
        }

    def gatingml(self):
        """Use XML-safe IDs and retain human labels in a comment and project JSON."""
        from lxml import etree
        mapping = {}
        for i, gate in enumerate(self.gates):
            slug = re.sub(r"[^A-Za-z0-9_]+", "_", gate.name).strip("_")[:50]
            mapping[gate.name] = f"g{i + 1:03d}_{slug or 'population'}"
        exported = [g.model_copy(update={"name": mapping[g.name], "parent": mapping.get(g.parent, "root")})
                    for g in self.gates]
        buffer = io.BytesIO()
        fk.export_gatingml(self.strategy(exported), buffer)
        root = etree.fromstring(buffer.getvalue())
        labels = " Aureka population label to XML identifier:\n" + json.dumps(mapping, ensure_ascii=False, indent=2) + " "
        root.insert(0, etree.Comment(labels.replace("--", "- -")))
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True), mapping
