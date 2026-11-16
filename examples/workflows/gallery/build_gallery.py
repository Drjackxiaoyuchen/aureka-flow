"""Reproduce four scientific figures from invented data; never reads lab files."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import platform
import sys

from aureka_flow.workflows.pipeline import write_run

if __package__:
    from .synthetic_data import build_dataset
else:
    from synthetic_data import build_dataset

FIGURES = [
    ("01-event-landscape", "Event landscape", "Shared-scale density plots of the first simulated acquisition in each condition, after the predefined time mask."),
    ("02-qc-and-selection", "QC and selection", "The known injected transient and exact event counts through a supplied mask and fluorescence rectangle."),
    ("03-replicate-comparison", "Acquisitions, not pooled-event inference", "Selected-event distributions beside one median for each of nine simulated acquisitions."),
    ("04-sortseq-linkage", "Sort-bin to decoded-count linkage", "A separate artificial count model: read fractions, read depths and declared sort counters are distinct quantities."),
]
INK = "#203641"
MUTED = "#566b75"
LINE = "#dbe4e8"
TEAL = "#147d82"
AMBER = "#c27b32"
COLORS = {"Baseline": "#7c8794", "Shift A": "#3983aa", "Shift B": TEAL}
COFACTOR = 20.0


def dependencies():
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LogNorm, LinearSegmentedColormap
    except ImportError as exc:
        raise RuntimeError("Install the plotting extra first: python -m pip install -e '.[docs]'") from exc
    return np, matplotlib, plt, LogNorm, LinearSegmentedColormap


def style(plt):
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11,
        "axes.titlesize": 13, "axes.titleweight": "normal", "axes.labelsize": 11,
        "text.color": INK, "axes.labelcolor": INK, "xtick.color": MUTED,
        "ytick.color": MUTED, "axes.edgecolor": LINE, "axes.linewidth": .8,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "svg.fonttype": "none",
        "svg.hashsalt": "yeast-facs-synthetic-gallery-v1",
    })


def frame(plt, number, title, subtitle, seed):
    fig = plt.figure(figsize=(13.8, 7.4))
    fig.text(.07, .945, f"YEAST FACS WORKFLOW  /  {number:02d}", fontsize=10, color=TEAL)
    fig.text(.07, .887, title, fontsize=23)
    fig.text(.07, .84, subtitle, fontsize=11, color=MUTED)
    fig.text(.07, .032, "SYNTHETIC ILLUSTRATION  ·  NOT EXPERIMENTAL DATA", fontsize=10, color=TEAL)
    fig.text(.95, .032, f"Seed {seed}  ·  software demonstration", ha="right", fontsize=10, color=MUTED)
    return fig


def signal_ticks(ax, np, axis="y"):
    low, high = ax.get_ylim() if axis == "y" else ax.get_xlim()
    candidates = [-100, -20, 0, 20, 100, 500, 2000, 10000]
    pairs = [(float(np.arcsinh(v / COFACTOR)), f"{v:,}") for v in candidates]
    pairs = [(v, label) for v, label in pairs if low <= v <= high]
    if axis == "y":
        ax.set_yticks([v for v, _ in pairs], [label for _, label in pairs])
    else:
        ax.set_xticks([v for v, _ in pairs], [label for _, label in pairs])


def padded(values, np, fraction=.06):
    low, high = float(np.min(values)), float(np.max(values))
    pad = (high - low) * fraction or 1.0
    return low - pad, high + pad


def landscape(data, np, plt, LogNorm):
    fig = frame(plt, 1, "Expression context changes how a signal is read",
                "Three programmed conditions · simulated acquisition 1 · all QC-retained events, before the expression gate",
                data["metadata"]["seed"])
    grid = fig.add_gridspec(1, 3, left=.075, right=.87, bottom=.24, top=.73, wspace=.16)
    chosen = [data["samples"][i] for i in (0, 3, 6)]
    clouds = [(np.log10(s["events"][s["qc_mask"], 2]),
               np.arcsinh(s["events"][s["qc_mask"], 3] / COFACTOR)) for s in chosen]
    xlim = padded(np.concatenate([x for x, _ in clouds]), np)
    ylim = padded(np.concatenate([y for _, y in clouds]), np)
    artists = []
    axes = []
    for index, (sample, (x, y)) in enumerate(zip(chosen, clouds)):
        ax = fig.add_subplot(grid[index])
        axes.append(ax)
        artist = ax.hexbin(x, y, gridsize=34, mincnt=1, cmap="viridis",
                           extent=(*xlim, *ylim), linewidths=0, norm=LogNorm(vmin=1))
        artists.append(artist)
        ax.axvline(np.log10(400), color=INK, ls=(0, (4, 3)), lw=1.1)
        ax.set(xlim=xlim, ylim=ylim)
        ticks = [v for v in [20, 50, 100, 400, 1000, 4000, 10000] if xlim[0] <= np.log10(v) <= xlim[1]]
        ax.set_xticks(np.log10(ticks), [f"{v:,}" for v in ticks], rotation=25)
        signal_ticks(ax, np)
        ax.set_title(sample["condition"], color=COLORS[sample["condition"]], loc="left", pad=13)
        if index == 0:
            ax.set_ylabel("APC-A · binding-like signal (a.u.; asinh)", labelpad=10)
        else:
            ax.tick_params(labelleft=False)
        ax.text(.02, .97, f'n = {int(sample["qc_mask"].sum()):,}', transform=ax.transAxes,
                va="top", fontsize=10, color=INK)
    norm = LogNorm(vmin=1, vmax=max(2, max(float(a.get_array().max()) for a in artists)))
    for artist in artists:
        artist.set_norm(norm)
    colorbar = fig.colorbar(artists[0], cax=fig.add_axes([.9, .24, .014, .49]))
    colorbar.set_label("Events / hexagon · log color scale", labelpad=10)
    fig.text(.46, .145, "FITC-A · expression-like signal (a.u.; log10)", ha="center", fontsize=11)
    fig.text(.07, .085, "Dashed line: supplied FITC-A ≥ 400 in linear units. Asinh cofactor = 20; negative APC-A values are retained.", fontsize=10, color=MUTED)
    return fig


def qc_and_selection(data, np, plt):
    sample = data["samples"][6]
    events = sample["events"]
    keep = sample["qc_mask"]
    fig = frame(plt, 2, "Make every exclusion and denominator visible",
                "Shift B · simulated acquisition 1 · the artifact location is known from construction, not automatically detected",
                data["metadata"]["seed"])
    grid = fig.add_gridspec(1, 2, left=.08, right=.95, bottom=.22, top=.73, width_ratios=[1.35, 1], wspace=.43)
    ax = fig.add_subplot(grid[0])
    ax.axvspan(80, 100, color=AMBER, alpha=.12)
    for mask, color, label in [(keep, TEAL, "Retained by supplied mask"), (~keep, AMBER, "Predetermined exclusion")]:
        ax.scatter(events[mask, 4], np.arcsinh(events[mask, 3] / COFACTOR),
                   s=4, alpha=.4, color=color, linewidths=0, label=label, rasterized=True)
    ax.set_xlabel("Synthetic acquisition time (s)", labelpad=9)
    ax.set_ylabel("APC-A (a.u.; asinh, cofactor 20)", labelpad=9)
    ax.set_title("A  /  Explicit time mask", loc="left", pad=14)
    signal_ticks(ax, np)
    ax.set_xlim(0, 180)
    ax.set_xticks([0, 40, 80, 100, 140, 180])
    ax.legend(loc="lower right", fontsize=9, frameon=False, markerscale=3)
    ax = fig.add_subplot(grid[1])
    stages = [len(events), int(keep.sum()), int(sample["selected_mask"].sum())]
    labels = ["All input", "After time mask", "+ FITC-A ≥ 400"]
    ax.barh(range(3), stages, height=.52, color=["#c6d1d7", "#79b5b7", TEAL])
    ax.set_yticks(range(3), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, stages[0] * 1.38)
    ax.set_ylim(2.7, -.7)
    ax.set_xlabel("Retained events (count)", labelpad=12)
    ax.set_title("B  /  Selection ledger", loc="left", pad=14)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    for index, count in enumerate(stages):
        ax.text(count + stages[0] * .035, index, f"{count:,}\n{count / stages[0]:.1%} of input",
                va="center", fontsize=10)
    fig.text(.08, .12, "Mask: exclude 80 ≤ time < 100 s. Rectangle: retain FITC-A ≥ 400. Both are illustrative, supplied decisions.", fontsize=11, color=MUTED)
    fig.text(.08, .085, "Retention is not a positive-cell fraction; selected events are not established live singlets.", fontsize=10, color=MUTED)
    return fig


def replicate_comparison(data, np, plt):
    fig = frame(plt, 3, "Event distributions and acquisition-level summaries",
                "After the predefined time mask and supplied expression rectangle · three simulated acquisitions per condition",
                data["metadata"]["seed"])
    grid = fig.add_gridspec(1, 2, left=.08, right=.95, bottom=.24, top=.73, wspace=.34)
    ax = fig.add_subplot(grid[0])
    arrays = {condition: np.concatenate([s["events"][s["selected_mask"], 3] for s in data["samples"]
                                         if s["condition"] == condition]) for condition in COLORS}
    transformed = {condition: np.arcsinh(values / COFACTOR) for condition, values in arrays.items()}
    domain = padded(np.concatenate(list(transformed.values())), np)
    bins = np.linspace(*domain, 65)
    peak_density = 0.0
    for condition, values in transformed.items():
        density, edges = np.histogram(values, bins=bins, density=True)
        peak_density = max(peak_density, float(density.max()))
        ax.stairs(density, edges, color=COLORS[condition], lw=2,
                  label=f"{condition} · {len(values):,} selected events")
    ax.set(xlim=domain, xlabel="APC-A (a.u.; asinh, cofactor 20)", ylabel="Density per transformed unit")
    ax.set_ylim(0, peak_density * 1.40)
    ax.set_title("A  /  Event-level distributions", loc="left", pad=14)
    signal_ticks(ax, np, axis="x")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax = fig.add_subplot(grid[1])
    measured = {s["sample_id"]: s for s in data["measurements"]["samples"]}
    markers = ["o", "s", "^"]
    all_values = []
    for index, condition in enumerate(COLORS):
        for rep, sample in enumerate([s for s in data["samples"] if s["condition"] == condition]):
            value = measured[sample["sample_id"]]["channels"]["APC-A"]["median"]
            all_values.append(float(np.arcsinh(value / COFACTOR)))
            ax.scatter(index + (rep - 1) * .13, np.arcsinh(value / COFACTOR), s=62,
                       marker=markers[rep], color=COLORS[condition], linewidths=0, zorder=3)
    ax.set_ylim(*padded(all_values, np, .16))
    ax.set_xlim(-.5, 2.5)
    ax.set_xticks(range(3), list(COLORS))
    signal_ticks(ax, np)
    tick_values = [50, 100, 200, 500, 1000]
    limits = ax.get_ylim()
    tick_values = [v for v in tick_values if limits[0] <= np.arcsinh(v / COFACTOR) <= limits[1]]
    ax.set_yticks(np.arcsinh(np.array(tick_values) / COFACTOR), [f"{v:,}" for v in tick_values])
    ax.set_ylabel("Per-acquisition median APC-A (a.u.; asinh)", labelpad=8)
    ax.set_title("B  /  One point per simulated acquisition", loc="left", pad=14)
    ax.grid(axis="y", color=LINE, linewidth=.7)
    for rep, marker in enumerate(markers, 1):
        ax.scatter([], [], s=42, color=MUTED, marker=marker, label=f"Simulated R{rep}")
    ax.legend(frameon=False, ncol=3, fontsize=9, loc="upper left", bbox_to_anchor=(-.02, -.12), handletextpad=.3, columnspacing=.8)
    fig.text(.08, .115, "Left: pooled events are displayed only to show distributions. Right: nine separate summaries; no confidence intervals or p-values.", fontsize=10, color=MUTED)
    fig.text(.08, .075, "Condition shifts were programmed into the model. Their separation is not an experimental finding or a performance benchmark.", fontsize=10, color=MUTED)
    return fig


def sortseq_linkage(data, np, plt, LinearSegmentedColormap):
    result = data["linked"]
    bins = result["bins"]
    variants = result["observed_variant_ids"]
    rows = {(row["variant_id"], row["bin_id"]): row for row in result["linked_counts"]}
    matrix = np.array([[100 * rows[(v, b["bin_id"])]["read_fraction_within_sequencing_sample"]
                        for b in bins] for v in variants])
    fig = frame(plt, 4, "Link identities without confusing reads and cells",
                "Eight invented variants · four categorical bins · counts generated independently of the simulated event clouds",
                data["metadata"]["seed"])
    grid = fig.add_gridspec(2, 2, left=.095, right=.95, bottom=.23, top=.735,
                            width_ratios=[1.1, 1], wspace=.45, hspace=.62)
    ax = fig.add_subplot(grid[:, 0])
    cmap = LinearSegmentedColormap.from_list("synthetic_teal", ["#f0f7f7", "#8ec9c7", "#125e65"])
    image = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=max(1, float(matrix.max())), aspect="auto")
    ax.set_xticks(range(4), [f"Bin {i}" for i in range(1, 5)])
    ax.set_yticks(range(len(variants)), [f"Variant {i:02d}" for i in range(1, len(variants) + 1)])
    ax.set_title("A  /  Read composition within each bin", loc="left", pad=14)
    ax.tick_params(length=0)
    for row in range(len(variants)):
        for column in range(len(bins)):
            value = matrix[row, column]
            label = "<0.1%" if 0 < value < .1 else "0%" if value == 0 else f"{value:.1f}%"
            ax.text(column, row, label, ha="center", va="center", fontsize=10,
                    color="white" if value > matrix.max() * .65 else INK)
    cb = fig.colorbar(image, ax=ax, fraction=.038, pad=.04)
    cb.set_label("Within-bin read fraction (%)", fontsize=10, labelpad=8)
    for row, key, title, label in [(0, "total_reads", "B  /  Sequencing depth", "Reads"),
                                     (1, "sorted_events", "C  /  Declared sort counters", "Sorted events")]:
        ax = fig.add_subplot(grid[row, 1])
        values = [b[key] for b in bins]
        ax.bar(range(4), values, color=TEAL if row == 0 else "#7f919d", width=.6)
        ax.set_xticks(range(4), [f"Bin {i}" for i in range(1, 5)])
        ax.set_ylabel(label)
        ax.set_ylim(0, max(values) * 1.28)
        ax.set_title(title, loc="left", pad=12)
        ax.ticklabel_format(axis="y", style="plain")
        for i, value in enumerate(values):
            ax.text(i, value + max(values) * .045, f"{value:,}", ha="center", fontsize=10)
    fig.text(.095, .12, "Column fractions total 100% before rounding. Read depth and sort counters use separate axes; neither normalizes the other.", fontsize=10, color=MUTED)
    fig.text(.095, .078, "No FASTQ decoding, event-to-variant recovery, cell-fraction correction, enrichment or affinity estimation is shown.", fontsize=10, color=MUTED)
    return fig


def page():
    cards = "".join(f'<section><h2>{html.escape(title)}</h2><p>{html.escape(caption)}</p><a href="figures/{name}.svg"><img src="figures/{name}.png" alt="Synthetic illustration: {html.escape(caption)}"></a></section>'
                    for name, title, caption in FIGURES)
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' data:; style-src \'unsafe-inline\'; base-uri \'none\'"><title>Synthetic yeast-FACS gallery</title><style>body{margin:0;background:#f3f7f8;color:#203641;font:16px/1.6 system-ui,sans-serif}main{max-width:1250px;margin:auto;padding:40px 24px}h1{font-size:38px;font-weight:600;letter-spacing:-.035em}h2{font-weight:500}p{max-width:1000px}nav{display:flex;gap:24px;flex-wrap:wrap;margin:25px 0}a{color:#126e76}section{margin:44px 0}img{width:100%;height:auto;border:1px solid #dbe4e8}.note{border-left:3px solid #147d82;padding:12px 20px;background:#e4f0f0}footer{font-size:13px;color:#566b75}@media(max-width:600px){h1{font-size:28px}main{padding:24px 14px}}</style></head><body><main><p>YEAST FACS WORKFLOW / SYNTHETIC GALLERY</p><h1>From event clouds to traceable summaries</h1><p class="note">Entirely simulated data. Programmed condition shifts, a predetermined QC mask and separately invented sequencing counts demonstrate software behavior—not biological validation.</p><nav><a href="workflow/index.html">Six-module workflow output</a><a href="summary.json">Numbers and simulation recipe</a><a href="gallery-manifest.json">File hashes and software versions</a></nav>' + cards + '<footer>Click a figure for its SVG. No laboratory data or private sample identities are included.</footer></main></body></html>'


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def build_gallery(output, *, seed=20261001, events_per_sample=3000):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("gallery output must be a fresh nonexistent directory")
    np, matplotlib, plt, LogNorm, LinearSegmentedColormap = dependencies()
    data = build_dataset(seed=seed, events_per_sample=events_per_sample)
    software = {"python": platform.python_version(), "numpy": np.__version__, "matplotlib": matplotlib.__version__}
    # Calculate and render before writing output files. Original inputs do not exist: all arrays are invented.
    with plt.rc_context():
        style(plt)
        figures = [landscape(data, np, plt, LogNorm), qc_and_selection(data, np, plt),
                   replicate_comparison(data, np, plt), sortseq_linkage(data, np, plt, LinearSegmentedColormap)]
        output.mkdir(parents=True, exist_ok=False)
        (output / "figures").mkdir()
        try:
            for (name, _, _), fig in zip(FIGURES, figures):
                fig.savefig(output / "figures" / (name + ".png"), dpi=180, metadata={"Software": "yeast-facs synthetic gallery"})
                svg_path = output / "figures" / (name + ".svg")
                fig.savefig(svg_path, metadata={"Date": None, "Creator": "yeast-facs synthetic gallery"})
                # Matplotlib emits trailing spaces inside multiline path data.
                # Normalize only that insignificant XML whitespace for clean diffs.
                svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
        finally:
            for fig in figures:
                plt.close(fig)
    write_run(output / "workflow", data["measurements"], data["manifest"], data["experiment"], data["linked"],
              (data["sort_bins"], data["variant_counts"]), synthetic=True)
    summary = {"schema_version": "yeast-facs-gallery-summary/v1", "evidence_kind": "synthetic",
               "software": software, "simulation": data["metadata"],
               "display_transforms": {"FITC-A": "log10; synthetic expression values are positive", "APC-A": "asinh(value / 20); preserves negative values; ticks labeled in original arbitrary units"},
               "counts": {"input": sum(s["event_count"] for s in data["measurements"]["samples"]),
                          "after_time_mask": sum(s["processing"]["stage_counts"]["after_external_qc_mask"] for s in data["measurements"]["samples"]),
                          "after_expression_gate": sum(s["selected_count"] for s in data["measurements"]["samples"])},
               "samples": [{"sample_id": s["sample_id"], "condition": s["condition"], "simulated_replicate": s["biological_replicate"],
                            "event_count": s["event_count"], "selected_count": s["selected_count"],
                            "channels": s["channels"], "source": s["source"]} for s in data["experiment"]["samples"]],
               "sort_bins": data["linked"]["bins"], "linked_counts": data["linked"]["linked_counts"],
               "comparison_status": data["experiment"]["comparison_status"], "biological_validation": False}
    write_json(output / "summary.json", summary)
    (output / "index.html").write_text(page(), encoding="utf-8")
    manifest = {"schema_version": "yeast-facs-gallery-manifest/v1", "evidence_kind": "synthetic", "seed": seed,
                "software": software, "file_hash_scope": "All generated files except this manifest itself; paths relative to the gallery output directory",
                "files": [{"path": p.relative_to(output).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in sorted(output.rglob("*")) if p.is_file()]}
    write_json(output / "gallery-manifest.json", manifest)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="fresh output directory; no overwrite")
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--events-per-sample", type=int, default=3000)
    args = parser.parse_args(argv)
    try:
        summary = build_gallery(args.output, seed=args.seed, events_per_sample=args.events_per_sample)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(args.output), "evidence_kind": "synthetic", "counts": summary["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
