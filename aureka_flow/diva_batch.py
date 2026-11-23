"""Stream an explicitly reviewed FACSDiva experiment into private local reports.

python -m aureka_flow.diva_batch --help
"""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .bd_workspace import DivaWorkspace, MAX_XML_BYTES, basename
from .config import MAX_FILE_BYTES
from .engine import AnalysisEngine
from .workflows.core.core import _ranges


def analyze_directory(xml_path, fcs_dir, output, *, worksheet="global:0", compensation="xml", acknowledged=False):
    if not acknowledged:
        raise ValueError("Acknowledge the reconstruction and source-compensation assumptions before analysis.")
    xml_path, fcs_dir, output = Path(xml_path), Path(fcs_dir), Path(output)
    with xml_path.open("rb") as handle:
        doc = DivaWorkspace(handle.read(MAX_XML_BYTES + 1), xml_path.name)
    doc.gates(worksheet, compensation)  # validate the chosen scope before creating output
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty output directory; existing files will not be overwritten.")
    output.mkdir(parents=True, exist_ok=True)
    rows, sources, bindings, errors = [], [], {}, []
    project = None
    selected = range(len(doc.tubes)) if worksheet.startswith("global:") else [int(worksheet.split(":")[1])]
    with (output / "membership-ranges.jsonl").open("w", encoding="utf-8") as membership:
        for index in selected:
            tube = doc.tubes[index]
            filename = basename(tube.findtext("data_filename", ""))
            try:
                if not filename or not filename.lower().endswith(".fcs"):
                    raise ValueError("XML sample has no usable FCS filename.")
                with (fcs_dir / filename).open("rb") as handle:
                    data = handle.read(MAX_FILE_BYTES + 1)
                engine = AnalysisEngine()
                info = engine.load(data, filename)
                del data  # one FCS file at a time, no all-experiment event array
                engine.import_workspace(doc, worksheet, "reconstructed", compensation, True)
                rec = engine.record(info["id"])
                events = engine.events(rec, compensation)
                project = project or engine.project()
                sources.append({**rec.info(), "fcs_metadata": rec.sample.get_metadata()})
                bindings[rec.digest] = index
                for population in engine.populations(rec):
                    mask = engine.mask(rec, population["name"])
                    indices = np.flatnonzero(mask)
                    row = {"sample": filename, "tube": tube.get("name", ""),
                           "well": rec.sample.metadata.get("well id", ""), "source_sha256": rec.digest,
                           "source_xml_sha256": doc.sha256, "compensation": compensation,
                           "evidence_kind": "user_data_reconstructed", "source_compensation_state": "unverified",
                           "population": population["name"], "parent": population["parent"] or "",
                           "count": population["count"], "total_events": rec.sample.event_count,
                           "parent_count": int(engine.mask(rec, population["parent"]).sum()) if population["parent"] else rec.sample.event_count,
                           "percent_total": population["percent_total"], "percent_parent": population["percent_parent"]}
                    for channel in rec.sample.pnn_labels:
                        values = events[mask, rec.sample.get_channel_index(channel)]
                        finite = values[np.isfinite(values)]
                        row[f"finite_count:{channel}"] = len(finite)
                        row[f"median:{channel}"] = float(np.median(finite)) if len(finite) else None
                    rows.append(row)
                    membership.write(json.dumps({"source_sha256": rec.digest, "population": population["name"],
                                                 "ranges": _ranges(indices.tolist()),
                                                 "semantics": "zero_based_original_FCS_DATA_order; start_inclusive_end_exclusive"}) + "\n")
            except (ValueError, OSError) as exc:
                errors.append({"sample": filename, "error": str(exc)})
    (output / "source-workspace.xml").write_bytes(doc.data)
    if project:
        project["samples"] = sources
        project["workspace"]["bindings"] = bindings
        (output / "aureka-project.json").write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
    if rows:
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with (output / "population-statistics.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        populations = list(dict.fromkeys(r["population"] for r in rows if r["population"] != "root"))
        fig = make_subplots(rows=2, cols=1, subplot_titles=("Population count · all parsed FCS events", "Percentage of immediate parent"), vertical_spacing=.18)
        palette = ["#4200ac", "#6fc0a9", "#9270cf", "#3d328f", "#a6d7c8", "#b49ae2", "#486a72", "#a583bb"]
        for i, name in enumerate(populations):
            values = [r for r in rows if r["population"] == name]
            labels = [r["tube"] + " · " + r["sample"].rsplit("_", 1)[-1].removesuffix(".fcs") for r in values]
            for axis, key in [(1, "count"), (2, "percent_parent")]:
                fig.add_trace(go.Scatter(x=labels, y=[r[key] for r in values], name=name,
                                        legendgroup=name, showlegend=axis == 1, mode="lines+markers",
                                        line={"color": palette[i % len(palette)]}), row=axis, col=1)
        fig.update_layout(template="plotly_white", height=1000, title="Aureka Flow · reconstructed instrument gates", hovermode="x unified", margin={"b": 150})
        fig.update_xaxes(tickangle=90)
        fig.update_yaxes(title_text="Events", row=1, col=1)
        fig.update_yaxes(title_text="% of parent", range=[0, 100], row=2, col=1)
        charts = fig.to_html(full_html=False, include_plotlyjs=True)
        header = ("<!doctype html><html><head><meta charset='utf-8'><title>Aureka Flow · instrument XML analysis</title></head><body style='font-family:system-ui;margin:32px;color:#30264d'>"
                  "<h1>Aureka Flow · instrument XML analysis</h1><p><b>Reconstructed results — comparison with FACSDiva counts pending.</b></p>"
                  f"<p>{len(sources)} FCS files analyzed; {len(errors)} file errors. Compensation: {html.escape(compensation)}. XML: {html.escape(doc.filename)} · SHA-256 {doc.sha256}.</p>"
                  "<p>Original XML, per-sample hashes, gate settings, full-event membership ranges and finite denominators accompany this report. No channel remapping was performed. Source compensation history remains unverified. Fluorescence does not establish affinity or cellular function.</p>")
        (output / "report.html").write_text(header + charts + "</body></html>", encoding="utf-8")
    receipt = {"source_xml_sha256": doc.sha256, "xml_version": doc.version,
               "samples_analyzed": len(sources), "population_rows": len(rows), "errors": errors,
               "compensation": compensation, "evidence_kind": "user_data_reconstructed",
               "reference_validation": "FACSDiva population-count comparison pending",
               "files": [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in sorted(output.iterdir()) if p.is_file()]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", required=True, type=Path)
    parser.add_argument("--fcs-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--worksheet", default="global:0")
    parser.add_argument("--compensation", choices=["xml", "fcs", "raw"], default="xml")
    parser.add_argument("--acknowledge-reconstruction", action="store_true")
    args = parser.parse_args()
    result = analyze_directory(args.xml, args.fcs_dir, args.output, worksheet=args.worksheet,
                               compensation=args.compensation, acknowledged=args.acknowledge_reconstruction)
    print(json.dumps({k: result[k] for k in ("samples_analyzed", "population_rows", "errors", "reference_validation")}))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
