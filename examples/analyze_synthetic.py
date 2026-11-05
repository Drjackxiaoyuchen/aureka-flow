"""Reproduce the GUI tutorial as code, using synthetic inputs only.

From a source checkout after `pip install .`:
    python examples/analyze_synthetic.py

Outputs stay in the ignored exports/ directory. No experimental files are read.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from aureka_flow.demo import demo_files
from aureka_flow.engine import AnalysisEngine, ComparisonSpec, ProjectSpec, ViewSpec

PURPLE, MINT, INK = "#4200AC", "#6FC0A9", "#33266C"


def analyze():
    """Load the same FCS bytes and exact saved gates used by the GUI guide."""
    engine = AnalysisEngine()
    samples = [engine.load(data, name, "SYNTHETIC code example; not experimental data")
               for name, data in demo_files()]
    project = ProjectSpec.model_validate_json((ROOT / "docs/tutorial-project.json").read_text(encoding="utf-8"))
    engine.set_gates(project.gates)
    expression_gate = next(g for g in project.gates if g.name == "Demo Expression+")
    spec = ComparisonSpec(sample_ids=[s["id"] for s in samples], x=expression_gate.x, y=expression_gate.y,
                          compensation=expression_gate.compensation, population="Demo Expression+", histogram_axis="y")
    comparison = engine.compare(spec)
    expected = json.loads((ROOT / "docs/tutorial-metrics.json").read_text(encoding="utf-8"))
    expected_by_name = {r["sample"]: r for r in expected["samples"]}
    populations, summary = [], []
    for sample in samples:
        rows = engine.populations(engine.record(sample["id"]))
        counts = {p["name"]: p["count"] for p in rows}
        reference = expected_by_name[sample["filename"]]
        for p in reference["populations"]:
            if counts[p["name"]] != p["count"]:
                raise ValueError(f"Demo result changed: {sample['filename']} / {p['name']}.")
        for p in rows:
            populations.append({"sample": sample["filename"], "source_sha256": sample["sha256"],
                                "synthetic": True, "compensation": spec.compensation,
                                **{key: p[key] for key in ("name", "parent", "count", "percent_parent", "percent_total")}})
        eplus = counts["Demo Expression+"]
        both = counts["Demo E+ B+"]
        median = next(r["median_y"] for r in comparison["rows"] if r["sample_id"] == sample["id"])
        if not np.isclose(median, reference["median_binding_logicle_in_expression_positive"], rtol=0, atol=1e-10):
            raise ValueError(f"Demo transformed median changed: {sample['filename']}.")
        summary.append({"sample": sample["filename"], "source_sha256": sample["sha256"],
                        "synthetic": True, "singlets": counts["Demo singlets"], "expression_positive": eplus,
                        "double_positive": both,
                        "double_positive_percent_of_singlets": 100 * both / counts["Demo singlets"],
                        "binding_positive_percent_of_expression_positive": 100 * both / eplus,
                        "median_binding_logicle_in_expression_positive": median})
    return engine, samples, spec, comparison, populations, summary


def plot_example(engine, samples, spec, comparison, destination):
    """A sampled scatter and full-event distributions, with Plotly bundled locally."""
    view = engine.view(ViewSpec(sample_id=samples[-1]["id"], x=spec.x, y=spec.y,
                                compensation=spec.compensation, population="Demo singlets"))
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=.15,
                        subplot_titles=("Binding demo · singlets", "Binding within Expression+ · all three demos"))
    fig.add_trace(go.Scattergl(x=view["x"], y=view["y"], mode="markers",
                              marker={"color": PURPLE, "size": 3, "opacity": .12}, showlegend=False,
                              name="Simulated events", hovertemplate="Expression %{x:.4f}<br>Binding %{y:.4f}<extra></extra>"), row=1, col=1)
    # The four saved quadrants share these boundaries in their saved Logicle coordinates.
    gate = next(g for g in engine.gates if g.name == "Demo E+ B+")
    fig.add_vline(x=gate.bounds[0], line_color=MINT, line_width=2, row=1, col=1)
    fig.add_hline(y=gate.bounds[2], line_color=MINT, line_width=2, row=1, col=1)
    for hist, color in zip(comparison["histograms"], ["#7E768E", MINT, PURPLE]):
        fig.add_trace(go.Scatter(x=hist["x"], y=hist["percent"], mode="lines", line={"color": color, "width": 2},
                                name=hist["sample"], hovertemplate="Binding %{x:.4f}<br>%{y:.3f}% / bin<extra>%{fullData.name}</extra>"),
                      row=1, col=2)
    fig.update_xaxes(title_text="Expression · Logicle coordinate", row=1, col=1)
    fig.update_yaxes(title_text="Binding · Logicle coordinate", row=1, col=1)
    fig.update_xaxes(title_text="Binding · Logicle coordinate", row=1, col=2)
    fig.update_yaxes(title_text="% of finite events per bin", rangemode="tozero", row=1, col=2)
    fig.update_layout(title={"text": "Aureka Flow · SYNTHETIC worked example", "font": {"color": PURPLE}},
                      template="plotly_white", height=650, font={"family": "Arial, sans-serif", "color": INK},
                      paper_bgcolor="#F7F6FB", margin={"l": 70, "r": 45, "t": 125, "b": 115},
                      legend={"orientation": "h", "x": .5, "xanchor": "center", "y": 1.17})
    fig.add_annotation(x=0, y=-.20, xref="paper", yref="paper", xanchor="left", showarrow=False,
                       text=f"Synthetic data only · scatter: {view['display_count']:,} / {view['population_count']:,} singlets displayed"
                            "<br>Gate statistics and histograms use full events. Histogram areas are normalized per sample.",
                       font={"size": 11, "color": "#77718B"}, align="left")
    html = fig.to_html(include_plotlyjs=True, full_html=True, config={"displaylogo": False, "responsive": True})
    html = html.replace("<head>", '<head><title>Aureka Flow · Synthetic analysis example</title>'
                        '<meta name="viewport" content="width=device-width, initial-scale=1">', 1)
    destination.write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "exports/synthetic-walkthrough",
                        help="Output directory (default: ignored exports/synthetic-walkthrough).")
    args = parser.parse_args()
    engine, samples, spec, comparison, populations, summary = analyze()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "population-counts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(populations[0]))
        writer.writeheader()
        writer.writerows(populations)
    project = engine.project()
    results = {"description": "SYNTHETIC demonstration; not experimental measurements", "software": project["software"],
               "population": spec.population, "axes_and_compensation": spec.model_dump(exclude={"sample_ids"}),
               "summary": summary, "comparison_rows": comparison["rows"]}
    for name, payload in [("analysis-summary.json", results), ("gate-project.json", project)]:
        (args.output / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    plot_example(engine, samples, spec, comparison, args.output / "interactive-analysis.html")
    print("SYNTHETIC demo · verified against every published population count")
    for row in summary:
        print(f"{row['sample']}: E+ B+ {row['double_positive']:,} / E+ {row['expression_positive']:,} = "
              f"{row['binding_positive_percent_of_expression_positive']:.2f}% binding-positive among expressers; "
              f"median binding (Logicle) {row['median_binding_logicle_in_expression_positive']:.6f}")
    print(f"Saved statistics, project, provenance and an offline interactive figure to {args.output.resolve()}")


if __name__ == "__main__":
    main()
