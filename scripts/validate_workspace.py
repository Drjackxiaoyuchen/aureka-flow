"""Compare an existing FlowJo workspace with fresh full-event FlowKit results.

Inputs are supplied explicitly. All reports stay on the local filesystem.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

import flowkit as fk
from lxml import etree


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(2**20), b""):
            value.update(chunk)
    return value.hexdigest()


def stored_counts(path):
    tree = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))
    counts, roots = {}, {}

    def walk(node, sample, ancestors=("root",)):
        for population in node.findall("./Subpopulations/Population"):
            name = population.get("name")
            if population.get("count") is not None:
                counts[(sample, name, ancestors)] = int(population.get("count"))
            walk(population, sample, ancestors + (name,))

    for sample in tree.findall(".//SampleList/Sample"):
        node = sample.find("SampleNode")
        if node is None:
            continue
        name = node.get("name")
        roots[name] = int(node.get("count")) if node.get("count") else None
        walk(node, name)
    return counts, roots, tree.getroot().get("flowJoVersion")


def percentage(count, denominator):
    return 100 * count / denominator if count is not None and denominator else None


def compare(workspace_path, fcs_dir, output):
    references, root_counts, flowjo_version = stored_counts(workspace_path)
    files = sorted(path for path in fcs_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".fcs")
    if not files:
        raise ValueError("No FCS files were found in the supplied directory.")
    paths = {}
    for path in files:
        if path.name in paths:
            raise ValueError(f"Ambiguous duplicate FCS filename: {path.name}")
        paths[path.name] = path
    workspace = fk.Workspace(str(workspace_path), fcs_samples=[str(p) for p in files], ignore_missing_files=True)
    workspace.analyze_samples(use_mp=False)
    output.mkdir(parents=True, exist_ok=True)
    rows, sources = [], []
    for sample_id in workspace.get_sample_ids():
        sample, results = workspace.get_sample(sample_id), workspace.get_gating_results(sample_id)
        root_matches = sample.event_count == root_counts.get(sample_id)
        sources.append({"sample": sample_id, "sha256": digest(paths[sample_id]),
                        "flowjo_total": root_counts.get(sample_id), "fcs_total": sample.event_count,
                        "root_counts_match": root_matches})
        for name, gate_path in workspace.get_gate_ids(sample_id):
            reference = references.get((sample_id, name, gate_path))
            computed = int(results.get_gate_count(name, gate_path))
            reference_parent = (root_counts.get(sample_id) if gate_path == ("root",)
                                else references.get((sample_id, gate_path[-1], gate_path[:-1])))
            computed_parent = (sample.event_count if gate_path == ("root",)
                               else int(results.get_gate_count(gate_path[-1], gate_path[:-1])))
            rp, cp = percentage(reference, reference_parent), percentage(computed, computed_parent)
            rows.append({"sample": sample_id, "gate_path": "/".join(gate_path[1:] + (name,)),
                         "flowjo_count": reference, "flowkit_count": computed,
                         "delta_events": computed - reference if reference is not None else None,
                         "flowjo_percent_parent": rp, "flowkit_percent_parent": cp,
                         "delta_parent_percentage_points": cp-rp if cp is not None and rp is not None else None,
                         "relative_count_difference_pct": 100*(computed-reference)/reference if reference else None,
                         "status": ("missing stored reference" if reference is None else
                                    "source root count differs" if not root_matches else "compared")})
    comparable = [row for row in rows if row["status"] == "compared"]
    missing = sorted(set(root_counts) - set(workspace.get_sample_ids()))
    summary = {
        "flowkit_version": fk.__version__, "flowjo_workspace_version": flowjo_version,
        "workspace_filename": workspace_path.name, "workspace_sha256": digest(workspace_path),
        "loaded_samples": len(sources), "unloaded_workspace_samples": missing,
        "total_events": sum(source["fcs_total"] for source in sources),
        "gate_sample_rows": len(rows), "comparable_rows": len(comparable),
        "exact_count_matches": sum(row["delta_events"] == 0 for row in comparable),
        "max_absolute_count_difference": max((abs(row["delta_events"]) for row in comparable), default=None),
        "max_absolute_parent_frequency_difference_pp": max((abs(row["delta_parent_percentage_points"])
              for row in comparable if row["delta_parent_percentage_points"] is not None), default=None),
        "sources": sources,
        "scope": "Replay of saved human gates. No independent human event masks or automatic gate selection are evaluated.",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if rows:
        with (output / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return rows, summary


def render(rows, summary, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    comparable = [row for row in rows if row["status"] == "compared"]
    plotted = [row for row in comparable if row["flowjo_count"] > 0 and row["flowkit_count"] > 0]
    fig, axis = plt.subplots(figsize=(7, 6))
    if plotted:
        axis.scatter([r["flowjo_count"] for r in plotted], [r["flowkit_count"] for r in plotted], color="#4200ac", s=24, alpha=.7)
        maximum = max(max(r["flowjo_count"], r["flowkit_count"]) for r in plotted)
        axis.plot([1, maximum*1.1], [1, maximum*1.1], color="#6fc0a9", linestyle="--")
        axis.set_xscale("log");axis.set_yscale("log")
    else:
        axis.text(.5,.5,"No comparable positive-count populations",ha="center",transform=axis.transAxes)
    axis.set(xlabel="Stored FlowJo count", ylabel="Fresh FlowKit count", title="Saved human-gate count comparison")
    fig.tight_layout();fig.savefig(output / "count_comparison.png", dpi=160);plt.close(fig)
    def number(value):
        return "unavailable" if value is None else f"{value:,.5f}".rstrip("0").rstrip(".")
    table = "".join("<tr>"+"".join(f"<td>{html.escape(str(value))}</td>" for value in [
        r["sample"],r["gate_path"],r["flowjo_count"],r["flowkit_count"],r["delta_events"],
        number(r["delta_parent_percentage_points"]),r["status"]])+"</tr>" for r in rows)
    content = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Aureka Flow validation</title><style>body{{margin:0;background:#f7f6fb;color:#33266c;font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}main{{max-width:1100px;margin:auto;padding:35px 24px}}a{{color:#4200ac}}p{{line-height:1.8}}img{{width:min(650px,100%);height:auto;background:white}}.table{{overflow:auto;background:white;border:1px solid #e6e1ef;border-radius:8px}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{padding:10px;border-bottom:1px solid #e6e1ef;text-align:left;white-space:nowrap}}.note{{border-left:3px solid #6fc0a9;padding:16px;background:white}}</style></head><body><main><a href="/">Open Aureka Flow analyzer</a><h1>Saved human-gate comparison</h1><p>{summary['loaded_samples']} samples; {summary['total_events']:,} FCS events; {summary['comparable_rows']} comparable gate/sample rows; {summary['exact_count_matches']} exact count matches.</p><p>Maximum difference in percent of parent: {number(summary['max_absolute_parent_frequency_difference_pp'])} percentage points. Unloaded workspace samples: {len(summary['unloaded_workspace_samples'])}.</p><p class="note">Original gate definitions are imported without count-based tuning. Differences are reported explicitly. Root-count mismatches and missing references are flagged. No independent human event memberships were supplied, so count agreement does not establish event-by-event equivalence. Automatic gate selection is not tested.</p><img src="count_comparison.png" alt="Stored human counts versus recomputed counts"><p><a href="comparison.csv">Comparison CSV</a> · <a href="summary.json">Summary and source hashes</a></p><div class="table"><table><thead><tr><th>Sample</th><th>Gate path</th><th>FlowJo</th><th>FlowKit</th><th>Delta events</th><th>Delta parent (pp)</th><th>Status</th></tr></thead><tbody>{table}</tbody></table></div></main></body></html>'''
    (output / "index.html").write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path, help="Human FlowJo .wsp file")
    parser.add_argument("--fcs-dir", required=True, type=Path, help="Directory containing the matching FCS files")
    parser.add_argument("--output", type=Path, default=Path("validation/workspace-report"))
    args = parser.parse_args()
    if not args.workspace.is_file() or not args.fcs_dir.is_dir():
        parser.error("Provide an existing workspace file and FCS directory.")
    rows, summary = compare(args.workspace, args.fcs_dir, args.output)
    render(rows, summary, args.output)
    print(f"{summary['comparable_rows']} comparisons; {summary['exact_count_matches']} exact count matches.")
    print(f"Local report: {args.output / 'index.html'}")


if __name__ == "__main__":
    main()
