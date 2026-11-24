"""Local, lossless FACSDiva XML preservation and reviewed gate reconstruction.

The Logicle scale reconstruction is a published interoperability convention,
not a claim of numerical identity with BD's proprietary display implementation.
See docs/BD_XML_IMPORT.md for source references and evidence limits.
"""
from __future__ import annotations

import base64
import hashlib
import math
from pathlib import PurePosixPath

from lxml import etree
import flowkit as fk
import numpy as np

MAX_XML_BYTES = 5 * 1024**2


def basename(name):
    return PurePosixPath(name.replace("\\", "/")).name


def flag(node, name):
    value = node.findtext(name)
    if value not in {"true", "false"}:
        raise ValueError(f"Missing or invalid FACSDiva flag: {name}.")
    return value == "true"


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("XML coordinate, scale or coefficient is missing or not numeric.") from exc
    if not math.isfinite(result):
        raise ValueError("XML coordinates, scales and compensation coefficients must be finite (non-finite value found).")
    return result


class DivaWorkspace:
    def __init__(self, data, filename="experiment.xml"):
        if not data or len(data) > MAX_XML_BYTES:
            raise ValueError("FACSDiva XML must be nonempty and at most 5 MB.")
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
        try:
            self.root = etree.fromstring(data, parser)
        except etree.XMLSyntaxError as exc:
            raise ValueError("Invalid experiment XML.") from exc
        if self.root.getroottree().docinfo.doctype or any(isinstance(n, etree._Entity) for n in self.root.iter()):
            raise ValueError("DTD and entity declarations are not accepted in experiment XML.")
        if self.root.tag != "bdfacs" or len(self.root.findall("experiment")) != 1:
            raise ValueError("Expected one FACSDiva bdfacs experiment; other XML formats are not interchangeable.")
        self.data, self.filename = data, basename(filename)
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.experiment = self.root.find("experiment")
        self.version = self.root.get("version", "unknown")
        self.tubes = self.experiment.findall(".//tube")
        if len(self.tubes) > 2000:
            raise ValueError("XML limit: 2,000 sample references.")
        self.sheets = {}
        for i, sheet in enumerate(self.experiment.findall("acquisition_worksheets/worksheet_template")):
            self.sheets[f"global:{i}"] = sheet
        for i, tube in enumerate(self.tubes):
            if any(g.get("type") != "EventSource_Classifier" for g in tube.findall("gates/gate")):
                self.sheets[f"tube:{i}"] = tube

    def source(self):
        return {"format": "bd-facsdiva-xml", "filename": self.filename,
                "sha256": self.sha256, "bytes_base64": base64.b64encode(self.data).decode("ascii")}

    @classmethod
    def from_source(cls, source):
        try:
            data = base64.b64decode(source["bytes_base64"], validate=True)
            doc = cls(data, source["filename"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid preserved FACSDiva XML source.") from exc
        if doc.sha256 != source.get("sha256"):
            raise ValueError("Preserved XML hash does not match its original bytes.")
        return doc

    def preview(self):
        return {"filename": self.filename, "sha256": self.sha256, "version": self.version,
                "experiment": self.experiment.get("name", ""),
                "samples": [{"index": i, "name": t.get("name", ""),
                             "filename": basename(t.findtext("data_filename", "")),
                             "instrument": t.findtext("data_instrument_name", ""),
                             "compensation_enabled": t.findtext("instrument_settings/compensation_enabled", "unknown")}
                            for i, t in enumerate(self.tubes)],
                "worksheets": [{"id": key, "name": s.get("name", ""),
                                "gate_records": len(s.findall("gates/gate"))}
                               for key, s in self.sheets.items()],
                "warnings": ["Original XML is preserved byte for byte, including unsupported settings and gates.",
                             "Reconstructed Logicle gates require independent count review; they are not validated Diva-equivalent results.",
                             "FACSDiva 8 experiment exports can swap height/width data. Check channel identities; no channels are remapped.",
                             "Filename matching is recorded with FCS hashes. XML and FCS GUIDs may differ; no GUID identity is inferred."]}

    def match(self, rec):
        matches = [i for i, t in enumerate(self.tubes)
                   if basename(t.findtext("data_filename", "")) == rec.filename]
        if len(matches) != 1:
            raise ValueError(f"{rec.filename}: expected one exact XML filename match, found {len(matches)}.")
        i = matches[0]
        reported = rec.sample.metadata.get("tube name")
        if reported and reported != self.tubes[i].get("name"):
            raise ValueError(f"{rec.filename}: FCS tube name conflicts with the XML sample identity.")
        return i

    def matrix(self, index):
        """Convert output-row compensation coefficients to a spillover matrix.

        Pulse-specific coefficient rows may describe independent A/H blocks.
        Their names and sizes must establish that contract without guessing.
        """
        settings = self.tubes[index].find("instrument_settings")
        if settings is None or not flag(settings, "compensation_enabled"):
            raise ValueError("This XML sample does not enable a compensation matrix.")
        params = [p for p in settings.findall("parameter") if p.find("compensation") is not None]
        names = [p.get("name") for p in params]
        if not names or None in names or len(set(names)) != len(names) or len(names) > 128:
            raise ValueError("XML compensation detector identities are missing or ambiguous.")
        coefficients = np.zeros((len(names), len(names)))
        for row, p in enumerate(params):
            values = [number(x.text) for x in p.findall("compensation/compensation_coefficient")]
            if len(values) == len(names):
                columns = list(range(len(names)))
            else:
                suffix = names[row].rsplit("-", 1)[-1]
                if suffix not in {"A", "H", "W"}:
                    raise ValueError("Cannot establish pulse-specific XML compensation columns.")
                columns = [i for i, name in enumerate(names) if name.endswith("-" + suffix)]
                if len(values) != len(columns):
                    raise ValueError("XML compensation coefficient count does not match detector order.")
            coefficients[row, columns] = values
        if not np.isfinite(coefficients).all() or np.linalg.cond(coefficients) > 1e10:
            raise ValueError("XML compensation matrix is non-finite or singular/ill-conditioned.")
        # Each XML row gives one output as a weighted sum of input detectors:
        # compensated = source @ coefficients.T. FlowKit expects spillover.
        return fk.Matrix(np.linalg.inv(coefficients.T), names, names)

    def gates(self, worksheet, compensation):
        from .engine import AxisSpec, GateSpec, TransformSpec

        if self.version not in {"Version 8.0", "Version 8.0.1"}:
            raise ValueError("Preserve this XML, but gate reconstruction currently supports Diva 8.0/8.0.1 only.")
        if worksheet not in self.sheets:
            raise ValueError("Choose a worksheet from this XML.")
        nodes = self.sheets[worksheet].findall("gates/gate")
        if len(nodes) > 101:
            raise ValueError("Workspace limit: 100 reconstructed populations.")
        binners = {g.get("fullname"): g for g in nodes
                   if g.get("type") == "Composite_Classifier" and g.find("region") is not None
                   and g.find("region").get("type") == "BINNER_REGION"}
        # Recognize an ordinary four-quadrant binner, not arbitrary composites.
        quadrants = {}
        for path, binner in binners.items():
            refs = [b.text for b in binner.findall("bin")]
            children = [g for g in nodes if g.get("fullname") in refs]
            if len(set(refs)) != 4 or len(children) != 4:
                raise ValueError("Unsupported composite classifier; preserve XML without reconstruction.")
            center = binner.find("region/points/point")
            if center is None:
                raise ValueError("Quadrant divider is missing.")
            seen = set()
            for child in children:
                region = child.find("region")
                points = region.findall("points/point") if region is not None else []
                if (region is None or region.get("type") != "POLYGON_REGION" or len(points) != 4
                        or child.findtext("input") != path or child.findtext("parent") != binner.findtext("parent")
                        or any(region.get(k) != binner.find("region").get(k) for k in ("xparm", "yparm"))):
                    raise ValueError("Unsupported quadrant child geometry.")
                xs = {number(p.get("x")) for p in points}; ys = {number(p.get("y")) for p in points}
                cx, cy = number(center.get("x")), number(center.get("y"))
                if len(xs) != 2 or len(ys) != 2 or cx not in xs or cy not in ys:
                    raise ValueError("Quadrant children do not share their divider.")
                side = (max(xs) > cx, max(ys) > cy)
                if xs != ({cx, 4095.0} if side[0] else {0.0, cx}) or ys != ({cy, 4095.0} if side[1] else {0.0, cy}):
                    raise ValueError("Unsupported quadrant outer limits.")
                seen.add(side)
                quadrants[child.get("fullname")] = (cx, cy, side)
            if len(seen) != 4:
                raise ValueError("Quadrant children do not partition the plane.")

        output, paths = [], {"All Events": "root"}
        labels = [g.findtext("name") for g in nodes if g.find("region") is not None and g.get("fullname") not in binners]
        for node in nodes:
            path = node.get("fullname")
            if node.get("type") == "EventSource_Classifier":
                if path != "All Events":
                    raise ValueError("Unsupported event source; preserve XML without reconstruction.")
                continue
            if path in binners:
                continue
            region = node.find("region")
            if node.get("type") != "Region_Classifier" or region is None:
                raise ValueError("Unsupported classifier; its original XML can still be preserved.")
            if path not in quadrants and not flag(node, "enabled"):
                raise ValueError("Disabled classifiers are preserved but require separate review before reconstruction.")
            if node.findtext("input") != node.findtext("parent") and path not in quadrants:
                raise ValueError("Gate input differs from its parent; automatic Boolean replay is unsupported.")
            parent = paths.get(node.findtext("parent"))
            if parent is None or path in paths:
                raise ValueError("Ambiguous or unordered XML gate ancestry.")
            name = node.findtext("name", "")
            if labels.count(name) > 1:
                name = f"Diva {len(output) + 1} · {name}"
            points = region.findall("points/point")
            if not points or len(points) > 1000:
                raise ValueError("Gate vertices are missing or exceed the limit.")
            coordinates, axes = [], []
            for axis in ("x", "y"):
                channel = region.get(f"{axis}parm")
                if not channel:
                    if axis == "x":
                        raise ValueError("Gate channel is missing.")
                    break
                scaled, logged = flag(node, f"is_{axis}_parameter_scaled"), flag(node, f"is_{axis}_parameter_log")
                values = np.array([number(p.get(axis)) for p in points])
                transform = TransformSpec()
                if logged:
                    if not scaled:
                        raise ValueError("Unscaled logarithmic gate coordinates need separate validation; XML is preservable.")
                    scale = number(node.findtext(f"{axis}_parameter_scale_value"))
                    if not math.isfinite(scale) or scale < 0:
                        raise ValueError("Gate-specific Diva scale value is unavailable.")
                    width = max(0, (4.5 - math.log10(262144 / scale)) / 2) if scale else 0
                    transform = TransformSpec(kind="logicle", t=262144, m=4.5, w=width, a=0)
                    values = values / 4096
                elif scaled:
                    values = values * 64  # 262144 / 4096, never a detector remapping
                if not np.isfinite(values).all():
                    raise ValueError("Gate coordinates must be finite.")
                axes.append(AxisSpec(channel=channel, transform=transform))
                coordinates.append(values.tolist())
            kind = region.get("type")
            common = dict(name=name, parent=parent, x=axes[0], y=axes[1] if len(axes) == 2 else None,
                          compensation=compensation)
            if path in quadrants:
                if not all(flag(node, f"is_{a}_parameter_scaled") for a in ("x", "y")):
                    raise ValueError("Unsupported unscaled quadrant geometry.")
                _, _, side = quadrants[path]
                bounds = []
                for values, positive in zip(coordinates, side):
                    bounds.extend([min(values), None] if positive else [None, max(values)])
                gate = GateSpec(kind="rectangle", bounds=bounds, **common)
            elif kind == "INTERVAL_REGION" and len(axes) == 1:
                gate = GateSpec(kind="range", bounds=[min(coordinates[0]), max(coordinates[0]), None, None], **common)
            elif kind == "POLYGON_REGION" and len(axes) == 2:
                gate = GateSpec(kind="polygon", vertices=list(zip(*coordinates)), **common)
            elif kind == "RECTANGLE_REGION" and len(axes) == 2:
                if len(set(coordinates[0])) != 2 or len(set(coordinates[1])) != 2:
                    raise ValueError("Rectangle corners are ambiguous.")
                gate = GateSpec(kind="rectangle", bounds=[min(coordinates[0]), max(coordinates[0]),
                                                         min(coordinates[1]), max(coordinates[1])], **common)
            else:
                raise ValueError(f"Unsupported region: {kind}. Its original XML can still be preserved.")
            paths[path] = name
            output.append(gate)
        if not output:
            raise ValueError("No reconstructable gates in the selected worksheet.")
        return output


def prepare_import(engine, doc, worksheet, mode, compensation, acknowledged=False, bindings=None):
    """Validate everything before committing any engine changes."""
    if mode not in {"preserve", "reconstructed"} or compensation not in {"raw", "fcs", "xml"}:
        raise ValueError("Invalid workspace import mode.")
    if mode == "reconstructed" and not acknowledged:
        raise ValueError("Review channel identity, source compensation and reconstruction limitations before applying gates.")
    if worksheet not in doc.sheets:
        raise ValueError("Select a worksheet from this XML.")
    if bindings is not None:
        bindings = dict(bindings)
    else:
        bindings = {}
        for rec in engine.samples.values():
            try:
                bindings[rec.digest] = doc.match(rec)
            except ValueError:
                if mode == "reconstructed":
                    raise
    if any(not isinstance(i, int) or i < 0 or i >= len(doc.tubes) for i in bindings.values()):
        raise ValueError("Invalid preserved XML sample binding.")
    if len(set(bindings.values())) != len(bindings):
        raise ValueError("Multiple FCS hashes map to the same XML sample; resolve ambiguous file identities before import.")
    if mode == "reconstructed":
        if worksheet.startswith("tube:") and any(i != int(worksheet.split(":")[1]) for i in bindings.values()):
            raise ValueError("A tube-specific worksheet can only be applied to its own matched FCS file.")
        if worksheet.startswith("global:") and any(
            g.get("type") != "EventSource_Classifier" for i in bindings.values() for g in doc.tubes[i].findall("gates/gate")
        ):
            raise ValueError("These samples have tube-specific gates. Review their individual worksheets instead of overriding them globally.")
    gates = doc.gates(worksheet, compensation) if mode == "reconstructed" else []
    workspace = {"source": doc.source(), "worksheet": worksheet, "mode": mode,
                 "compensation": compensation, "bindings": bindings,
                 "reconstruction_note": "Published Logicle reconstruction; independent Diva counts not yet verified. "
                                        "No detector remapping. Compensation is applied once to source values."}
    matrices = {}
    for rec in engine.samples.values():
        if rec.digest not in bindings:
            continue
        if compensation == "xml" and mode == "reconstructed":
            matrices[rec.uid] = doc.matrix(bindings[rec.digest])
            if not set(matrices[rec.uid].detectors).issubset(rec.sample.pnn_labels):
                raise ValueError(f"{rec.filename}: XML compensation detectors do not match FCS channels.")
        for gate in gates if mode == "reconstructed" else []:
            for axis in (gate.x, gate.y):
                if axis and axis.channel not in rec.sample.pnn_labels:
                    raise ValueError(f"{rec.filename}: gate channel '{axis.channel}' is missing; no automatic remapping.")
            if compensation == "fcs":
                engine.events(rec, "fcs")
    engine.strategy(gates)
    return workspace, gates, matrices
