"""Describe two CC-BY public bacterial FCS acquisitions from Ross (2021).

This original plotting script does not run FlowGateNIST, infer gates, apply
compensation, or reproduce its fitted Gaussian mixtures. It reads only a local,
hash-pinned supplementary ZIP; it never downloads files or executes archive code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import tempfile
import zipfile

from aureka_flow.workflows.core.core import analyze_fcs, inspect_fcs

SOURCE = {
    "citation": "David Ross (2021), Automated analysis of bacterial flow cytometry data with FlowGateNIST",
    "paper_doi": "10.1371/journal.pone.0250753",
    "dataset_doi": "10.1371/journal.pone.0250753.s001",
    "dataset_metadata_url": "https://api.figshare.com/v2/articles/15210195",
    "download_url": "https://ndownloader.figshare.com/files/29190015",
    "author_repository": "https://github.com/djross22/flowgatenist",
    "license": "CC-BY-4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "archive_basename": "pone.0250753.s001.zip",
    "archive_bytes": 22764704,
    "archive_md5": "0faf828873bb46c8809e09956a6069c6",
    "archive_sha256": "349feafb438e2b47675ad461fb781b34e7d3b423abe700f55e23c8bc94aa6cf3",
    "identity_evidence": "Paper Figure 2 caption identifies panel A as buffer blank and panels B-D as E. coli; SI ReadMe.txt maps raw FCS names to those figures.",
}
FILES = {
    "Fig 2A.fcs": {
        "sample_id": "ross2021-buffer-blank", "label": "Buffer blank",
        "sha256": "bd1059990d612565a1c42cc1e99de1d4f9ae23a9c479041c9ebef3aabdfe078f",
        "bytes": 2240224, "events": 13899,
        "role": "Matched buffer blank acquired before cell sample; paper Figure 2A",
        "acquisition_volume_ul_paper": 150,
    },
    "Fig 2BCD.fcs": {
        "sample_id": "ross2021-ecoli-cells", "label": "E. coli cell sample",
        "sha256": "afe9f8cd5a594a2ecb461ed32909cd882134a98556c1551e83039df5a39af2bc",
        "bytes": 10526624, "events": 65689,
        "role": "E. coli MG1655 delta-lac sample; paper Figure 2B-D, zero IPTG condition",
        "acquisition_volume_ul_paper": 25,
    },
}
CHANNELS = ["FSC-H", "SSC-H", "BL1-A", "Time"]
COFACTOR = 150.0
INK, MUTED, TEAL, GRAY = "#203641", "#566b75", "#147d82", "#8a929d"


def verified_members(source_zip):
    """Read exactly two fixed members; no extractall, symlinks, or path traversal."""
    source_zip = Path(source_zip)
    if source_zip.stat().st_size != SOURCE["archive_bytes"]:
        raise ValueError("Source archive size does not match the publisher deposit")
    payload = source_zip.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SOURCE["archive_sha256"]:
        raise ValueError("Source archive SHA-256 does not match the pinned deposit")
    if hashlib.md5(payload).hexdigest() != SOURCE["archive_md5"]:
        raise ValueError("Source archive MD5 does not match the publisher checksum")
    result = {}
    with zipfile.ZipFile(source_zip) as archive:
        names = archive.namelist()
        for name, expected in FILES.items():
            if names.count(name) != 1:
                raise ValueError("Missing or duplicate selected FCS member")
            info = archive.getinfo(name)
            if info.file_size != expected["bytes"] or info.is_dir():
                raise ValueError("Unexpected selected member size or type")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Selected member must not be a symlink")
            raw = archive.read(name)
            if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
                raise ValueError("Selected FCS SHA-256 does not match the pinned file")
            result[name] = raw
    return result


def load_data(source_zip, scratch_parent):
    import numpy as np
    import flowkit

    records = []
    with tempfile.TemporaryDirectory(prefix=".ross2021-fcs-", dir=scratch_parent) as temp:
        for name, raw in verified_members(source_zip).items():
            path = Path(temp) / name
            path.write_bytes(raw)
            mapping = FILES[name]
            sample = flowkit.Sample(str(path), sample_id=mapping["sample_id"], preprocess=True)
            events = sample.get_events(source="raw")
            if events.shape != (mapping["events"], 40):
                raise ValueError("Decoded shape differs from the independently inspected source")
            if int(sample.metadata["tot"]) != len(events):
                raise ValueError("Header and decoded event counts differ")
            values = {c: events[:, sample.pnn_labels.index(c)] for c in CHANNELS}
            if not all(np.isfinite(v).all() for v in values.values()):
                raise ValueError("Nonfinite plotting values require explicit handling")
            if not all((values[c] > 0).all() for c in ("FSC-H", "SSC-H")):
                raise ValueError("Scatter log10 display requires strictly positive values; do not silently discard events")
            config = {
                "schema_version": "yeast-facs-analysis-config/v1",
                "sample_id": mapping["sample_id"], "evidence_kind": "user_data",
                "channels": CHANNELS,
                "compensation": {"state": "uncompensated", "reason": "Descriptive public-data display; embedded spillover is not applied. No biological fluorescence comparison is inferred."},
            }
            # Schema v1 calls all measured events user_data; the outer provenance
            # below is authoritative about public origin, never synthetic/private.
            try:
                inspection = inspect_fcs(path)
                core = analyze_fcs(path, config)
                core_status = {"state": "executed", "inspection": inspection, "measurement": core}
                measured = core["samples"][0]
                if measured["event_count"] != len(events) or measured["selected_count"] != len(events):
                    raise AssertionError("Core analysis changed the all-event denominator")
                for channel in CHANNELS:
                    if not np.isclose(measured["channels"][channel]["median"], np.median(values[channel]), rtol=0, atol=1e-12):
                        raise AssertionError("Core median and plotted values disagree")
            except ValueError as exc:
                # Real FCS compatibility limitations remain explicit; never make
                # the stand-alone decoder look like a successful core run.
                core_status = {"state": "not_executed", "reason": str(exc),
                               "fallback": "Native FlowKit decode for descriptive plotting only"}
            summary = {
                "source_basename": name, **mapping,
                "event_count_decoded": len(events), "detector_count": events.shape[1],
                "metadata": {k: sample.metadata.get(k) for k in ("date", "btim", "etim", "timestep")},
                "embedded_spillover_present": bool(sample.metadata.get("spillover") or sample.metadata.get("spill")),
                "compensation_applied": False, "gating_applied": False,
                "event_exclusion": "none", "core_execution": core_status,
                "channels": {c: {"median": float(np.median(v)), "min": float(np.min(v)),
                                  "max": float(np.max(v)), "negative_count": int((v < 0).sum()),
                                  "finite_count": int(np.isfinite(v).sum())} for c, v in values.items()},
            }
            records.append({"values": values, "summary": summary})
    return records


def signal_ticks(ax, np, axis):
    candidates = [-10000, -1000, 0, 1000, 10000, 100000, 1000000]
    lo, hi = ax.get_xlim() if axis == "x" else ax.get_ylim()
    ticks = [(float(np.arcsinh(v / COFACTOR)), f"{v:,}") for v in candidates]
    ticks = [(x, text) for x, text in ticks if lo <= x <= hi]
    if axis == "x":
        ax.set_xticks([x for x, _ in ticks], [s for _, s in ticks], rotation=25)
    else:
        ax.set_yticks([x for x, _ in ticks], [s for _, s in ticks])


def draw(records, output):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
        "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": "#dbe4e8", "axes.spines.top": False,
        "axes.spines.right": False, "axes.titlesize": 12,
        "svg.fonttype": "none", "svg.hashsalt": "ross2021-public-fcs-v1",
    })
    fig = plt.figure(figsize=(13.8, 9.3), facecolor="white")
    fig.text(.07, .955, "YEAST FACS WORKFLOW  /  PUBLIC-DATA METHOD DEMO", color=TEAL, fontsize=10)
    fig.text(.07, .909, "Real acquisitions make analysis choices inspectable", fontsize=23)
    fig.text(.07, .872, "Ross (2021) · E. coli and a buffer blank · bacterial reference, not a yeast benchmark", color=MUTED, fontsize=11)
    grid = fig.add_gridspec(2, 2, left=.085, right=.86, top=.795, bottom=.235, hspace=.55, wspace=.28)
    clouds = [(np.log10(r["values"]["FSC-H"]), np.log10(r["values"]["SSC-H"])) for r in records]
    xlim = (min(float(x.min()) for x, _ in clouds) - .08, max(float(x.max()) for x, _ in clouds) + .08)
    ylim = (min(float(y.min()) for _, y in clouds) - .08, max(float(y.max()) for _, y in clouds) + .08)
    artists = []
    for i, (record, (x, y)) in enumerate(zip(records, clouds)):
        ax = fig.add_subplot(grid[0, i])
        artists.append(ax.hexbin(x, y, gridsize=44, extent=(*xlim, *ylim), mincnt=1,
                                 cmap="viridis", linewidths=0, norm=LogNorm(vmin=1)))
        ax.set(xlim=xlim, ylim=ylim, xlabel="FSC-H (a.u.; log10)", ylabel="SSC-H (a.u.; log10)")
        ax.set_xticks([3, 4, 5, 6], ["1,000", "10,000", "100,000", "1,000,000"])
        ax.set_yticks([3, 4, 5, 6], ["1,000", "10,000", "100,000", "1,000,000"])
        ax.set_title(f'{chr(65+i)}  {record["summary"]["label"]}', loc="left", pad=12)
        ax.text(.02, .96, f'n = {len(x):,} events · ungated', va="top", transform=ax.transAxes,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .87, "pad": 3})
    ax = fig.add_subplot(grid[1, 0])
    transformed = [np.arcsinh(r["values"]["BL1-A"] / COFACTOR) for r in records]
    bins = np.linspace(min(float(v.min()) for v in transformed), max(float(v.max()) for v in transformed), 72)
    for record, values, color in zip(records, transformed, [GRAY, TEAL]):
        ax.hist(values, bins=bins, weights=np.full(len(values), 100 / len(values)),
                histtype="step", lw=1.8, color=color, label=record["summary"]["label"])
    ax.set_title("C  Detector distributions, not binding", loc="left", pad=12)
    ax.set(xlabel="BL1-A (a.u.; asinh)", ylabel="Events / bin (% of acquisition)")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    signal_ticks(ax, np, "x")
    ax = fig.add_subplot(grid[1, 1])
    values = records[1]["values"]
    artists.append(ax.hexbin(values["Time"], transformed[1], gridsize=44, mincnt=1,
                             cmap="viridis", linewidths=0, norm=LogNorm(vmin=1)))
    ax.set_title("D  Cell-sample acquisition profile", loc="left", pad=12)
    ax.set(xlabel="Time (s; metadata-scaled)", ylabel="BL1-A (a.u.; asinh)")
    signal_ticks(ax, np, "y")
    norm = LogNorm(vmin=1, vmax=max(float(a.get_array().max()) for a in artists))
    for artist in artists:
        artist.set_norm(norm)
    colorbar = fig.colorbar(artists[0], cax=fig.add_axes([.89, .255, .013, .475]))
    colorbar.set_label("Events / hexagon · log color scale", labelpad=12)
    fig.text(.07, .117, "All original events retained. No gates, compensation or automatic QC exclusions; negative BL1-A values preserved.", fontsize=10, color=MUTED)
    fig.text(.07, .087, "Asinh cofactor 150 a.u. · Blank/cell acquisition volumes differ (150/25 µL); counts are not concentration estimates.", fontsize=10, color=MUTED)
    fig.text(.07, .043, "DATA: DAVID ROSS (2021) · CC BY 4.0 · DOI: 10.1371/journal.pone.0250753.s001", fontsize=9, color=TEAL)
    fig.text(.07, .020, "New descriptive replot from raw FCS; not a reproduction of the author's fitted gating analysis.", fontsize=9, color=MUTED)
    for suffix in ("png", "svg"):
        path = output / f"03-public-fcs-qc.{suffix}"
        metadata = {"Creator": "yeast-facs-workflow; data David Ross, CC BY 4.0"}
        if suffix == "svg":
            metadata["Date"] = None
        fig.savefig(path, dpi=180, metadata=metadata)
        if suffix == "svg":
            path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)


def build(source_zip, output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new output directory; existing outputs are never overwritten")
    if ".." in output.parts or any(p.is_symlink() for p in output.absolute().parents):
        raise ValueError("Output must not traverse symlink parents or '..' components")
    # Reject nonmatching archives before creating even an empty output directory.
    verified_members(source_zip)
    import numpy as np
    import flowkit
    import matplotlib

    output.mkdir(parents=True)
    records = load_data(source_zip, output)
    summary = {
        "schema_version": "yeast-facs-public-fcs-demo/v1", "evidence_kind": "public_experimental_data",
        "organism": "Escherichia coli", "yeast_data": False, "source": SOURCE,
        "software": {"python": platform.python_version(), "flowkit": flowkit.__version__,
                     "numpy": np.__version__, "matplotlib": matplotlib.__version__},
        "processing": "Native FlowKit preprocess=True: amplification, gain and Time metadata scaling; source='raw' means uncompensated, not byte-identical detector storage.",
        "display": {"scatter": "log10 positive FSC-H/SSC-H", "BL1-A": "asinh", "cofactor": COFACTOR,
                    "histogram": "72 edges shared by both acquisitions; per-bin percent, not density per linear a.u.",
                    "subsampling": "none"},
        "interpretation_limits": ["Bacterial example, not yeast validation", "One cell acquisition and one blank, not biological replicates",
                                  "No cell, singlet, positive or negative biological gate is inferred",
                                  "Embedded spillover is recorded but not applied", "No inference of affinity, viability, concentration or QC pass/fail",
                                  "No FlowGateNIST algorithms were executed; this is not an author-analysis reproduction"],
        "samples": [r["summary"] for r in records],
    }
    draw(records, output)
    summary["derived_files"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                for p in sorted(output.glob("03-public-fcs-qc.*"))}
    (output / "flowgatenist-summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", required=True, type=Path, help="Local publisher ZIP; exact checksums are verified")
    parser.add_argument("--output", required=True, type=Path, help="A fresh output directory")
    args = parser.parse_args()
    result = build(args.source_zip, args.output)
    print(json.dumps({"organism": result["organism"], "dataset_doi": SOURCE["dataset_doi"],
                      "samples": [{"file": s["source_basename"], "events": s["event_count_decoded"],
                                   "core_state": s["core_execution"]["state"]} for s in result["samples"]]}, indent=2))
