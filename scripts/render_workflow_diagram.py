#!/usr/bin/env python3
"""Render the repository's editable workflow SVG and high-resolution PNG.

Run after installing the gallery extra (Python 3.12+):
    python scripts/render_workflow_diagram.py

This documentation renderer reads no experimental files. It intentionally replaces
only workflow-overview.svg and workflow-overview.png in the output directory.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch


WIDTH, HEIGHT = 1200, 1810
INK = "#183B43"
BODY = "#405C65"
TEAL = "#16776E"
LINE = "#BACFD0"
PALE = "#F3F8F8"
AMBER = "#9D6815"
AMBER_PALE = "#FFF8E9"
AMBER_LINE = "#E7CCA0"
BLUE = "#397691"


def build_figure():
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none",
                         "svg.hashsalt": "yeast-facs-workflow-diagram-v1"})
    fig = plt.figure(figsize=(12, HEIGHT / 100), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, WIDTH), ylim=(HEIGHT, 0))
    ax.set_axis_off()

    def text(x, y, label, size=20, color=BODY, weight="normal", **kwargs):
        # One diagram coordinate equals 0.72 points at the authored size.
        return ax.text(x, y, label, fontsize=size * .72, color=color,
                       fontweight=weight, va="top", **kwargs)

    def box(x, y, width, height, fill="white", edge=LINE, dashed=False, radius=12):
        patch = FancyBboxPatch((x, y), width, height,
                               boxstyle=f"round,pad=0,rounding_size={radius}",
                               facecolor=fill, edgecolor=edge, linewidth=1,
                               linestyle=(0, (5, 4)) if dashed else "solid")
        ax.add_patch(patch)
        return patch

    def arrow(points, color=TEAL, dashed=False):
        xs, ys = zip(*points)
        if len(points) > 2:
            ax.plot(xs[:-1], ys[:-1], color=color, linewidth=1.65,
                    linestyle=(0, (4, 3)) if dashed else "solid")
        ax.add_patch(FancyArrowPatch(points[-2], points[-1],
                                    arrowstyle="-|>", mutation_scale=12,
                                    linewidth=1.65, color=color,
                                    linestyle=(0, (4, 3)) if dashed else "solid",
                                    shrinkA=0, shrinkB=0))

    def stage(number, title, y, lines, footer, height=148):
        box(56, y, 744, height, PALE)
        ax.add_patch(Circle((99, y + 42), 25, facecolor=TEAL, edgecolor="none"))
        text(99, y + 25, f"{number:02}", 25, "white", "bold", ha="center")
        text(146, y + 23, title, 27, INK, "bold")
        for i, line in enumerate(lines):
            text(146, y + 65 + 29 * i, line, 20)
        text(146, y + height - 30, footer, 18, TEAL)

    def review(y, title, lines, height=148):
        box(850, y, 294, height, AMBER_PALE, AMBER_LINE)
        text(872, y + 22, title, 20, AMBER, "bold")
        for i, line in enumerate(lines):
            text(872, y + 58 + 27 * i, line, 18.5, BODY)
        ax.plot([813, 838], [y + height / 2] * 2,
                color=AMBER_LINE, linewidth=1.3, linestyle=(0, (3, 3)))

    text(56, 36, "YEAST FACS WORKFLOW", 18, TEAL, "bold")
    text(56, 70, "From acquisition to traceable evidence", 38, INK, "bold")
    text(56, 121, "Six connected responsibilities · explicit decisions · inspectable artifacts", 22)

    box(56, 171, 1088, 72, fill="#F6F8FA", edge="#D6DFE4")
    text(78, 187, "YOU SUPPLY", 17, INK, "bold")
    text(217, 183, "run.json · FCS files · processing config · samples.json", 22, INK)
    text(217, 214, "Assay design, control qualification and biological interpretation remain human work.", 18)

    text(56, 273, "IMPLEMENTED EXECUTION + FILE CONTRACTS", 18, TEAL, "bold")
    text(850, 273, "HUMAN CROSS-CHECKS", 18, AMBER, "bold")
    text(850, 299, "Advisory, not execution gates", 17, BODY)

    stage(1, "Ingest & identify", 336,
          ["Inspect FCS HEADER/TEXT; hash original bytes.",
           "Reject duplicate content and malformed input."],
          "Identity: acquisition → sample ID → recorded source hash")
    review(336, "Confirm identity", ["Correct sample mapping;",
                                    "genuine biological-replicate", "IDs, not event counts."])
    arrow([(428, 484), (428, 518)])

    stage(2, "Inspect acquisition quality", 520,
          ["Time / non-finite diagnostics do not auto-filter.",
           "External mask: check source hash, count and indices."],
          "Mask interface only · no native PeacoQC execution")
    review(520, "Inspect exclusions", ["Review time warnings and",
                                       "any external event mask."])
    arrow([(428, 668), (428, 702)])

    stage(3, "Declare processing & selection", 704,
          ["Explicit compensation choice + supplied rectangles.",
           "Track input → mask → selected → finite denominators."],
          "FlowKit native path · linear fluorescence gate coordinates")
    review(704, "Check measurements", ["Review controls and units.",
                                         "Selected events are not", "automatically live singlets."])
    arrow([(428, 852), (428, 877)])
    box(56, 879, 744, 50, fill="#E3F1EE", edge="#94BDB5")
    text(79, 894, "measurements.json", 21, TEAL, "bold")
    text(338, 895, "Medians + hashes + processing lineage", 18, INK)
    text(56, 943, "01–03 are logical responsibilities, not exact call order:", 17)
    text(56, 968, "FlowKit preprocessing / compensation precedes event summarization.", 17)
    arrow([(428, 992), (428, 1019)])

    stage(4, "Assemble the experiment", 1021,
          ["Join measurements + samples.json by exact sample ID.",
           "Check replicate / batch metadata; preserve restrictions."],
          "Cross-batch blocked ≠ execution failure; status flows downstream",
          height=148)
    review(1021, "Check comparability", ["Review batch / replicate",
                                              "flags; reference labels", "do not calibrate batches."])

    # Both report and optional linkage consume the experiment; stage 6 is not
    # downstream of the rendered report. The side inputs enter stage 6 only.
    arrow([(428, 1169), (428, 1195), (311, 1195), (311, 1270)])
    arrow([(428, 1195), (596, 1195), (596, 1386), (626, 1386)])
    text(56, 1226, "EXPERIMENT READOUT", 18, TEAL, "bold")
    box(626, 1199, 518, 54, fill="white", edge=BLUE, dashed=True)
    text(647, 1212, "sort-bins.json + decoded counts.json", 21, BLUE)
    arrow([(885, 1253), (885, 1269)], color=BLUE, dashed=True)

    box(56, 1272, 510, 239, fill=PALE)
    ax.add_patch(Circle((98, 1314), 24, facecolor=TEAL, edgecolor="none"))
    text(98, 1297, "05", 25, "white", "bold", ha="center")
    text(140, 1297, "Report & inspect", 27, INK, "bold")
    text(80, 1348, "Descriptive sample medians + warnings", 20)
    text(80, 1384, "05-report/experiment.json", 21, TEAL)
    text(80, 1417, "05-report/report.html", 21, TEAL)
    text(80, 1450, "REVIEW · medians, denominators, warnings", 17, AMBER)
    text(80, 1475, "No significance tests or automatic normalization", 16)

    box(626, 1272, 518, 239, fill=PALE)
    ax.add_patch(Circle((668, 1314), 24, facecolor=TEAL, edgecolor="none"))
    text(668, 1297, "06", 25, "white", "bold", ha="center")
    text(710, 1297, "Link sort-seq · optional", 26, INK, "bold")
    text(650, 1348, "Join experiment, bins and decoded counts", 20)
    text(650, 1377, "REVIEW · bin IDs, missing rows, count totals", 17.5, AMBER)
    text(650, 1411, "06-sortseq/linked_counts.json", 21, TEAL)
    text(650, 1444, "06-sortseq/report.html", 21, TEAL)
    text(650, 1471, "No FASTQ / Kd inference; reads ≠ sorted events", 16)

    arrow([(311, 1511), (311, 1530), (600, 1530), (600, 1546)])
    arrow([(885, 1511), (885, 1530), (600, 1530)])
    box(56, 1548, 1088, 84, fill="#E3F1EE", edge="#94BDB5")
    text(78, 1567, "run-receipt.json", 23, TEAL, "bold")
    text(302, 1565, "Hashes produced files + records module / comparison status", 22, INK)
    text(302, 1598, "Collects output provenance; does not approve an assay or choose a next experiment.", 18)

    ax.plot([56, 1144], [1660, 1660], color=LINE, linewidth=1)
    text(56, 1677, "INTEGRATION STATUS", 17, INK, "bold")
    ax.add_patch(Circle((68, 1721), 7, facecolor=TEAL, edgecolor="none"))
    text(87, 1709, "Reused runtime: FlowKit / FlowIO / FlowUtils", 18, INK)
    ax.plot([508, 533], [1721, 1721], color=BLUE, linewidth=2, linestyle=(0, (4, 3)))
    text(544, 1709, "Supplied file interface: masks / decoded counts", 18, INK)
    text(56, 1750, "Future adapters are not executed: PeacoQC, FlowCal, FlowGateNIST, wellmap, R workspaces, affinity models.", 17)
    text(56, 1780, "SOFTWARE CHECKS ≠ BIOLOGICAL VALIDATION", 17, TEAL, "bold")
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "docs" / "workflows" / "figures")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    stem = args.output_dir / "workflow-overview"
    fig.savefig(stem.with_suffix(".png"), dpi=200, facecolor="white")
    fig.savefig(stem.with_suffix(".svg"), facecolor="white", metadata={"Date": None})
    plt.close(fig)
    svg = stem.with_suffix(".svg")
    content = svg.read_text(encoding="utf-8")
    # Retain editable text while giving assistive technologies a summary of the
    # topology and the important distinction between execution and human review.
    root_end = content.index(">", content.index("<svg")) + 1
    content = content[:root_end] + """
 <title id="workflow-title">Six connected responsibilities in the yeast FACS workflow</title>
 <desc id="workflow-description">User-supplied FCS, configuration and sample metadata
 feed ingest, acquisition diagnostics and declared selection. These logical stages
 produce measurements.json. FlowKit preprocessing and compensation occur before
 event summarization; quality diagnostics do not automatically remove events.
 Experiment assembly joins sample metadata and preserves comparison restrictions.
 It branches to a descriptive report and, optionally, sort-bin and decoded-count
 linkage. The run receipt hashes produced files. Amber human-review notes are
 advisory, not software approval gates. Future upstream adapters are not executed.</desc>
""" + content[root_end:]
    content = content.replace("<svg ", '<svg role="img" aria-labelledby="workflow-title workflow-description" ', 1)
    svg.write_text("\n".join(line.rstrip() for line in content.splitlines()) + "\n", encoding="utf-8")
    print(f"Rendered {stem.with_suffix('.svg').name} and {stem.with_suffix('.png').name}")


if __name__ == "__main__":
    main()
