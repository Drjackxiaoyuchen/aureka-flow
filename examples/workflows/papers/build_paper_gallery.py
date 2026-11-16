"""Replot published Table 1 summaries; no affinity fitting or raw-data analysis.

Requires the gallery extra. Read-only input and fresh output directory only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from examples.workflows.papers.extract_adams_table import validate_data

FIGURES = ("01-published-method-comparison", "02-published-clone-intervals")
INK, MUTED, TEAL, BLUE, GRID = "#193C43", "#536972", "#168378", "#376B9C", "#DBE4E7"


def quantified_pairs(data):
    return [row for row in data["rows"] if all(row[method]["qualifier"] == "estimate" for method in ("flow", "titeseq"))]


def prepare_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#B2C2C6")
    ax.tick_params(colors=MUTED, labelsize=11)
    ax.grid(color=GRID, lw=.65)
    ax.set_axisbelow(True)


def heading(fig, number, title, subtitle):
    fig.text(.065, .955, f"PUBLISHED DATA / {number}", color=TEAL, fontsize=10, weight="bold")
    fig.text(.065, .910, title, color=INK, fontsize=21, weight="bold")
    fig.text(.065, .871, subtitle, color=MUTED, fontsize=11)
    fig.text(.065, .048, "Adams et al. · eLife 2016 · Table 1 · doi:10.7554/eLife.23156.018 · CC BY 4.0", color=MUTED, fontsize=9)
    fig.text(.065, .023, "Original replot of published estimates · not new affinity fits or a validation of this workflow", color=TEAL, fontsize=9)


def comparison(data):
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(12.8, 7.6), facecolor="white")
    heading(fig, "01", "Published affinity estimates, compared", "Anti-fluorescein scFvs displayed on yeast · conventional flow cytometry versus Tite-Seq")
    ax = fig.add_axes([.10, .19, .47, .63])
    prepare_axes(ax)
    ax.set(xlim=(-9.75, -4.55), ylim=(-9.75, -4.55), aspect="equal")
    ax.plot([-9.75, -4.55], [-9.75, -4.55], color="#94A8AE", lw=1.2, ls="--", zorder=1)
    rows = quantified_pairs(data)
    for row in rows:
        flow, tite = row["flow"], row["titeseq"]
        color = TEAL if row["clone"] == "WT" else BLUE
        ax.errorbar(flow["log10_kd_m"], tite["log10_kd_m"], xerr=flow["sem_log10"], yerr=tite["sem_log10"],
                    fmt="o", color=color, ecolor=color, markersize=7 if row["clone"] == "WT" else 5,
                    capsize=2.5, lw=1.05, alpha=.90, zorder=3)
    offsets = {"WT": (12, -20), "C107": (9, 12), "C22": (10, -15), "C102": (10, 11)}
    for row in rows:
        if row["clone"] in offsets:
            ax.annotate(row["clone"], (row["flow"]["log10_kd_m"], row["titeseq"]["log10_kd_m"]),
                        xytext=offsets[row["clone"]], textcoords="offset points", fontsize=10,
                        color=INK, arrowprops={"arrowstyle": "-", "color": MUTED, "lw": .5})
    ax.set_xlabel(r"Flow cytometry · $\log_{10}(K_D/\mathrm{M})$", fontsize=12, color=INK, labelpad=12)
    ax.set_ylabel(r"Tite-Seq · $\log_{10}(K_D/\mathrm{M})$", fontsize=12, color=INK, labelpad=10)
    sections = [
        (.74, "14 quantified clone pairs", "Both methods report a mean and standard error.\nFive limit-qualified clones are shown in Figure 02."),
        (.57, "Uncertainty stays visible", "Error bars are the published SEM in log10 units.\nDashed line: equal reported estimates, not a fitted model."),
        (.40, "Disagreement is inspectable", "WT, C107, C22 and C102 are labeled for lookup.\nEvery clone is retained in the paired interval plot and JSON."),
        (.23, "A bounded comparison", "No correlation-based validation claim, new fit or\nreconstruction of event-level gates is made here."),
    ]
    for y, title, body in sections:
        fig.text(.635, y, title, fontsize=13, color=INK, weight="bold")
        fig.text(.635, y - .045, body, fontsize=10.5, color=MUTED, linespacing=1.65, va="top")
    return fig


def intervals(data):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig = plt.figure(figsize=(12.8, 10), facecolor="white")
    heading(fig, "02", "Every clone, including reported detection limits", "Published log10 affinity estimates ± SEM · all 19 clones in the source-table order")
    ax = fig.add_axes([.16, .205, .65, .595])
    prepare_axes(ax)
    ax.set_xlim(-10.08, -4.35)
    ax.set_ylim(18.8, -.8)
    ax.set_yticks(range(19), [row["clone"] for row in data["rows"]])
    ax.grid(axis="y", visible=False)
    for limit in (-9.5, -5.0):
        ax.axvline(limit, color="#9BAAAF", lw=.9, ls=":")
    for i, row in enumerate(data["rows"]):
        if i % 2 == 0:
            ax.axhspan(i - .46, i + .46, color="#F3F7F7", zorder=0)
        for method, offset, color, marker in (("flow", -.14, TEAL, "o"), ("titeseq", .14, BLUE, "s")):
            value, y = row[method], i + offset
            x = value["log10_kd_m"]
            if value["qualifier"] == "estimate":
                ax.errorbar(x, y, xerr=value["sem_log10"], fmt=marker, color=color, ecolor=color,
                            capsize=2.2, markersize=4.8, lw=1.05, zorder=3)
            else:
                direction = -1 if value["qualifier"] == "approximately_at_or_below" else 1
                ax.plot(x, y, marker=marker, mfc="white", mec=color, ms=5, zorder=3)
                ax.annotate("", xy=(x + direction * .32, y), xytext=(x, y),
                            arrowprops={"arrowstyle": "->", "color": color, "lw": 1.25})
        ax.text(1.045, i, str(row["flow_replicates"]), transform=ax.get_yaxis_transform(),
                ha="center", va="center", fontsize=10.5, color=MUTED)
    ax.text(1.045, 1.036, "Flow n", transform=ax.transAxes, fontsize=10.5, color=INK, ha="center")
    ax.set_xlabel(r"Reported $\log_{10}(K_D/\mathrm{M})$ · lower values mean stronger affinity", fontsize=12, color=INK, labelpad=12)
    legend = [Line2D([0], [0], marker="o", color=TEAL, lw=1, label="Flow cytometry"),
              Line2D([0], [0], marker="s", color=BLUE, lw=1, label="Tite-Seq (n = 3)")]
    fig.legend(handles=legend, frameon=False, loc="upper left", bbox_to_anchor=(.15, .852), ncol=2, fontsize=11)
    fig.text(.16, .105, "Open markers + arrows preserve the reported ≲ / ≳ limits. Arrow length is illustrative, not an uncertainty interval.",
             fontsize=10, color=MUTED)
    fig.text(.16, .080, "Dotted lines mark the source's approximate sensitivity boundaries (−9.5 and −5.0). No SEM is invented for bound-only values.",
             fontsize=10, color=MUTED)
    return fig


def build(input_path, output):
    data_bytes = Path(input_path).read_bytes()
    data = json.loads(data_bytes)
    validate_data(data)
    output = Path(output)
    if output.exists() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("output must be a fresh nonexistent directory")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": "adams-table1-replot-v1"})
    output.mkdir(parents=True)
    for name, renderer in zip(FIGURES, (comparison, intervals)):
        figure = renderer(data)
        figure.savefig(output / (name + ".png"), dpi=180, facecolor="white")
        figure.savefig(output / (name + ".svg"), facecolor="white", metadata={"Date": None})
        plt.close(figure)
        svg = output / (name + ".svg")
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    summary = {"schema": "yeast-facs.paper-replot.v1", "evidence_kind": "published_summary",
               "source_table_sha256": hashlib.sha256(data_bytes).hexdigest(), "paper": data["paper"],
               "source": data["source"], "clones": len(data["rows"]), "quantified_pairs": len(quantified_pairs(data)),
               "limit_qualified_clones": [r["clone"] for r in data["rows"] if r not in quantified_pairs(data)],
               "error_bars": "Published SEM of log10(KD/M), not confidence intervals",
               "software": {"python": platform.python_version(), "matplotlib": matplotlib.__version__},
               "new_affinity_fits": False, "raw_fcs_reprocessed": False, "workflow_biological_validation": False}
    summary["derived_files"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                for p in sorted(output.iterdir()) if p.suffix in {".png", ".svg"}}
    (output / "adams-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).parent / "data/adams-2016-table1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.input, args.output)
    print(f"Replotted {result['clones']} published clones; {result['quantified_pairs']} quantified pairs. No new fits.")


if __name__ == "__main__":
    main()
