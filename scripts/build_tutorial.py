"""Build the public guide and figures using only the seeded, synthetic demo.

Run from a source checkout: pip install '.[docs]' && python scripts/build_tutorial.py
No experimental files are read. Plot annotations use the application's full-event
FlowKit results; independent NumPy masks check the intended demo geometry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import flowkit as fk
import markdown
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator
import numpy as np

from aureka_flow import __version__
from aureka_flow.demo import demo_files
from aureka_flow.engine import AnalysisEngine, AxisSpec, ComparisonSpec, GateSpec, QuadrantsSpec, TransformSpec

ASSETS = ROOT / "aureka_flow/static/assets"
DOCS = ROOT / "docs"
PURPLE, MINT, INK, MUTED = "#4200AC", "#6FC0A9", "#33266C", "#77718B"
BG, LINE, LAVENDER, PALE = "#F7F6FB", "#E6E1EF", "#AA8BD9", "#E9E4F1"
SAMPLE_COLORS = ["#7E768E", MINT, PURPLE]
SAMPLE_NAMES = ["Control", "Expression", "Binding"]
CELL_BOUNDS = (40000, 130000, 5000, 75000)
SINGLET_VERTICES = [(40000, 29000), (130000, 110000), (130000, 124000), (40000, 43000)]
E_THRESHOLD, B_THRESHOLD = .45, .38
DENSITY = LinearSegmentedColormap.from_list("aureka", ["#DCEFE9", MINT, "#9270C8", PURPLE])

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.labelcolor": MUTED, "axes.edgecolor": LINE, "axes.linewidth": .8,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "none",
    "svg.hashsalt": "aureka-flow-synthetic-tutorial",
    "savefig.facecolor": BG,
})


def analyze():
    engine = AnalysisEngine()
    infos = [engine.load(data, name, "SYNTHETIC tutorial; not experimental measurements")
             for name, data in demo_files()]
    linear = TransformSpec()
    logicle = TransformSpec(kind="logicle")
    fsc = AxisSpec(channel="FSC-A", transform=linear)
    ssc = AxisSpec(channel="SSC-A", transform=linear)
    height = AxisSpec(channel="FSC-H", transform=linear)
    expr = AxisSpec(channel="Expression-A", transform=logicle)
    bind = AxisSpec(channel="Binding-A", transform=logicle)
    uid = infos[-1]["id"]
    engine.add_gate(GateSpec(name="Demo cells", kind="rectangle", x=fsc, y=ssc, bounds=CELL_BOUNDS), uid)
    engine.add_gate(GateSpec(name="Demo singlets", parent="Demo cells", kind="polygon", x=fsc, y=height,
                             vertices=SINGLET_VERTICES), uid)
    engine.add_quadrants(QuadrantsSpec(sample_id=uid, prefix="Demo", parent="Demo singlets", x=expr, y=bind,
                                      expression_threshold=E_THRESHOLD, binding_threshold=B_THRESHOLD))
    rows = []
    for info in infos:
        rec = engine.record(info["id"])
        pops = {p["name"]: p for p in engine.populations(rec)}
        raw = engine.events(rec, "raw")
        f, s, h = raw[:, 0], raw[:, 1], raw[:, 2]
        cells = (f >= 40000) & (f < 130000) & (s >= 5000) & (s < 75000)
        singlets = cells & (h >= .9 * f - 7000) & (h <= .9 * f + 7000)
        x, y = engine.axis(rec, expr, "raw"), engine.axis(rec, bind, "raw")
        epos, bpos = singlets & (x >= E_THRESHOLD), singlets & (y >= B_THRESHOLD)
        assert np.array_equal(cells, engine.mask(rec, "Demo cells"))
        assert np.array_equal(singlets, engine.mask(rec, "Demo singlets"))
        assert np.array_equal(epos, engine.mask(rec, "Demo Expression+"))
        assert np.array_equal(epos & bpos, engine.mask(rec, "Demo E+ B+"))
        quadrants = [engine.mask(rec, f"Demo {q}") for q in ["E− B−", "E+ B−", "E− B+", "E+ B+"]]
        assert np.array_equal(np.sum(quadrants, axis=0), singlets.astype(int))
        e = pops["Demo Expression+"]["count"]
        both = pops["Demo E+ B+"]["count"]
        rows.append({"sample": info["filename"], "sha256": info["sha256"], "synthetic": True,
                     "populations": [{k: p[k] for k in ("name", "parent", "count", "percent_parent", "percent_total")}
                                     for p in pops.values()],
                     "binding_positive_percent_of_expression_positive": 100 * both / e,
                     "median_binding_logicle_in_expression_positive": float(np.median(y[epos]))})
    comparison = engine.compare(ComparisonSpec(sample_ids=[i["id"] for i in infos], x=expr, y=bind,
                                               population="Demo Expression+", histogram_axis="y"))
    return engine, infos, rows, comparison, expr, bind


def text(fig, x, y, value, size=11, color=INK, weight="normal", **kwargs):
    return fig.text(x, y, value, fontsize=size, color=color, weight=weight, **kwargs)


def card(fig, xywh, color="white", edge=LINE, radius=.018):
    x, y, w, h = xywh
    fig.add_artist(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.008,rounding_size={radius}",
                                 linewidth=.8, edgecolor=edge, facecolor=color, transform=fig.transFigure, zorder=-1))


def header(fig, title, subtitle, number):
    text(fig, .055, .944, "AUREKA  /  FLOW", 12, PURPLE, "bold")
    text(fig, .945, .944, f"GUIDE FIGURE {number}  ·  SYNTHETIC", 9, MUTED, ha="right")
    text(fig, .055, .875, title, 27, INK, "bold")
    text(fig, .055, .833, subtitle, 11, MUTED)


def footer(fig, value="Seeded simulation · full-event analysis · no experimental data or affinity measurements"):
    text(fig, .055, .028, value, 8, MUTED)
    text(fig, .945, .028, "aureka-flow", 9, PURPLE, "bold", ha="right")


def style(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel, fontsize=9, labelpad=7)
    ax.set_ylabel(ylabel, fontsize=9, labelpad=7)
    ax.set_facecolor("white")
    ax.tick_params(length=3)


def density(ax, x, y, extent, gridsize=55):
    ax.hexbin(x, y, gridsize=gridsize, extent=extent, mincnt=1, cmap=DENSITY, norm=LogNorm(), linewidths=0)
    ax.set_xlim(extent[:2])
    ax.set_ylim(extent[2:])


def thousands(ax):
    formatter = FuncFormatter(lambda v, _: f"{v / 1000:g}k")
    ax.xaxis.set_major_formatter(formatter)
    ax.yaxis.set_major_formatter(formatter)


def histogram(ax, comparison, compact=False):
    for hist, label, color in zip(comparison["histograms"], SAMPLE_NAMES, SAMPLE_COLORS):
        ax.plot(hist["x"], hist["percent"], color=color, lw=2.2, label=f"{label} demo")
        ax.fill_between(hist["x"], hist["percent"], color=color, alpha=.06)
    ax.axvline(B_THRESHOLD, color=LAVENDER, lw=1.1, ls=(0, (3, 3)))
    ax.set_xlim(-.08, 1.02)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_locator(MaxNLocator(4, integer=True))
    style(ax, "Binding · Logicle coordinate", "% of finite events / bin")
    ax.legend(frameon=False, fontsize=7.5 if compact else 9, loc="upper right", labelcolor=INK)


def save(fig, name):
    for ext in ("svg", "png"):
        path = ASSETS / f"tutorial-{name}.{ext}"
        fig.savefig(path, dpi=180,
                    metadata={"Creator": "Aureka Flow synthetic tutorial", "Date": None} if ext == "svg" else
                    {"Software": "Aureka Flow synthetic tutorial"})
        if ext == "svg":
            path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n")
    plt.close(fig)


def overview(engine, infos, rows, comparison, expr, bind):
    fig = plt.figure(figsize=(16, 8.5), facecolor=BG)
    header(fig, "Your data. Your gates. Your readout.",
           "A local workspace for expression × binding analysis, powered by FlowKit.", "01")
    rec = engine.record(infos[-1]["id"])
    raw = engine.events(rec, "raw")
    singlets = engine.mask(rec, "Demo singlets")
    titles = [("01", "Inspect events", "FCS files → scatter and source details"),
              ("02", "Define populations", "Rectangle, polygon and quadrant gates"),
              ("03", "Compare binding", "One strategy, applied to every sample")]
    for i, (num, title, subtitle) in enumerate(titles):
        x = .05 + i * .307
        card(fig, (x, .205, .286, .555))
        text(fig, x + .018, .717, num, 11, PURPLE, "bold")
        text(fig, x + .052, .717, title, 16, INK, "bold")
        text(fig, x + .018, .68, subtitle, 9, MUTED)
    ax = fig.add_axes([.099, .315, .213, .305])
    density(ax, raw[:, 0], raw[:, 1], (0, 160000, 0, 100000))
    ax.add_patch(Rectangle((40000, 5000), 90000, 70000, fc="none", ec=PURPLE, lw=1.8))
    style(ax, "FSC-A · linear", "SSC-A · linear")
    thousands(ax)
    cells = rows[-1]["populations"][1]["count"]
    text(fig, .068, .236, f"{cells:,} / 30,000 events in Demo cells", 10, PURPLE, "bold")
    ax = fig.add_axes([.406, .315, .213, .305])
    density(ax, engine.axis(rec, expr, "raw")[singlets], engine.axis(rec, bind, "raw")[singlets],
            (.12, .95, -.1, 1.02))
    ax.axvline(E_THRESHOLD, color=PURPLE, lw=1.6)
    ax.axhline(B_THRESHOLD, color=PURPLE, lw=1.6)
    style(ax, "Expression · Logicle", "Binding · Logicle")
    ax.text(.97, .95, "E+ B+", transform=ax.transAxes, ha="right", va="top", color=PURPLE, fontsize=10, weight="bold")
    text(fig, .375, .236, "Control-derived thresholds for real experiments", 9, PURPLE, "bold")
    ax = fig.add_axes([.713, .315, .213, .305])
    histogram(ax, comparison, compact=True)
    text(fig, .682, .236, "Binding distributions within Expression+", 10, PURPLE, "bold")
    card(fig, (.05, .092, .9, .07), color=PURPLE, edge=PURPLE)
    text(fig, .071, .12, "Full-event counts", 11, "white", "bold")
    text(fig, .30, .12, "Source hashes", 11, "white", "bold")
    text(fig, .51, .12, "Reusable gate templates", 11, "white", "bold")
    text(fig, .928, .12, "30,000 simulated events / sample", 9, "#D9CCEE", ha="right")
    footer(fig)
    save(fig, "overview")


def gating(engine, infos, rows, comparison, expr, bind):
    fig = plt.figure(figsize=(16, 11.7), facecolor=BG)
    header(fig, "Build a gate hierarchy you can explain.",
           "Exact geometry is supplied in the tutorial project. Gate sizes below refer to the Binding demo.", "02")
    rec = engine.record(infos[-1]["id"])
    raw = engine.events(rec, "raw")
    pops = {p["name"]: p for p in rows[-1]["populations"]}
    for x, y, number, title, sub in [
        (.05, .458, "01", "Scatter gate", "Parent: All events · linear / uncompensated"),
        (.515, .458, "02", "Singlet band", "Parent: Demo cells · linear / uncompensated"),
        (.05, .075, "03", "Expression × binding", "Parent: Demo singlets · Logicle / uncompensated"),
        (.515, .075, "04", "Binding among expressers", "Population: Demo Expression+ · full-event histograms")]:
        card(fig, (x, y, .435, .338))
        text(fig, x + .018, y + .301, number, 11, PURPLE, "bold")
        text(fig, x + .054, y + .301, title, 15, INK, "bold")
        text(fig, x + .018, y + .276, sub, 9, MUTED)
    ax = fig.add_axes([.112, .523, .33, .197])
    density(ax, raw[:, 0], raw[:, 1], (0, 160000, 0, 100000), 65)
    ax.add_patch(Rectangle((40000, 5000), 90000, 70000, fc="none", ec=PURPLE, lw=1.8))
    style(ax, "FSC-A", "SSC-A"); thousands(ax)
    p = pops["Demo cells"]
    text(fig, .068, .477, f"{p['count']:,} cells-gate events · {p['percent_parent']:.2f}% of all events", 10, PURPLE, "bold")
    ax = fig.add_axes([.577, .523, .33, .197])
    mask = engine.mask(rec, "Demo cells")
    density(ax, raw[mask, 0], raw[mask, 2], (30000, 140000, 20000, 140000), 65)
    ax.add_patch(Polygon(SINGLET_VERTICES, fc="none", ec=PURPLE, lw=1.8))
    style(ax, "FSC-A", "FSC-H"); thousands(ax)
    p = pops["Demo singlets"]
    text(fig, .533, .477, f"{p['count']:,} band events · {p['percent_parent']:.2f}% of Demo cells", 10, PURPLE, "bold")
    ax = fig.add_axes([.112, .145, .33, .192])
    mask = engine.mask(rec, "Demo singlets")
    density(ax, engine.axis(rec, expr, "raw")[mask], engine.axis(rec, bind, "raw")[mask],
            (.12, .95, -.1, 1.02), 65)
    ax.axvline(E_THRESHOLD, color=PURPLE, lw=1.6)
    ax.axhline(B_THRESHOLD, color=PURPLE, lw=1.6)
    for suffix, x, y, ha, va in [("E− B−", .03, .04, "left", "bottom"), ("E+ B−", .97, .04, "right", "bottom"),
                                ("E− B+", .03, .96, "left", "top"), ("E+ B+", .97, .96, "right", "top")]:
        p = pops[f"Demo {suffix}"]
        ax.text(x, y, f"{suffix}\n{p['percent_parent']:.1f}%", transform=ax.transAxes, fontsize=9,
                color=PURPLE, weight="bold", ha=ha, va=va,
                bbox={"fc": "white", "ec": "none", "alpha": .86, "pad": 2})
    style(ax, "Expression · Logicle coordinate", "Binding · Logicle coordinate")
    text(fig, .068, .094, "X ≥ 0.45 = E+    /    Y ≥ 0.38 = B+    /    percentages of singlets", 9, PURPLE, "bold")
    ax = fig.add_axes([.577, .145, .33, .192])
    histogram(ax, comparison)
    text(fig, .533, .094, "Equal histogram area compares shape; it does not show population yield.", 9, PURPLE, "bold")
    footer(fig, "Synthetic illustration · no viability or debris/aggregate mixture is simulated · demo thresholds are arbitrary")
    save(fig, "gating")


def denominators(rows):
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    header(fig, "Same events. Different denominators.",
           "Always name the parent population when reporting a positive fraction.", "03")
    card(fig, (.05, .16, .40, .605))
    card(fig, (.477, .16, .473, .605))
    text(fig, .07, .719, "Follow the population path", 16, INK, "bold")
    text(fig, .07, .682, "Binding demo · exact full-event counts", 10, MUTED)
    pops = {p["name"]: p for p in rows[-1]["populations"]}
    chain = ["root", "Demo cells", "Demo singlets", "Demo Expression+", "Demo E+ B+"]
    for i, name in enumerate(chain):
        y = .587 - i * .084
        label = "All events" if name == "root" else name.removeprefix("Demo ")
        if name == "Demo E+ B+":
            label = "E+ B+ (subset of Expression+)"
        card(fig, (.078 + i * .009, y, .337 - i * .009, .061), color=PURPLE if i == 4 else BG,
             edge=PURPLE if i == 4 else LINE, radius=.008)
        text(fig, .09 + i * .009, y + .035, label, 9.5, "white" if i == 4 else INK, "bold")
        text(fig, .399, y + .013, f"{pops[name]['count']:,}", 13, "white" if i == 4 else PURPLE,
             "bold", ha="right")
        if i < 4:
            fig.add_artist(FancyArrowPatch((.105 + i * .009, y - .002), (.105 + i * .009, y - .02),
                                           arrowstyle="-|>", mutation_scale=9, color=LAVENDER,
                                           transform=fig.transFigure))
    text(fig, .07, .187, "The supplied E+ B+ gate is saved under Demo singlets.", 9, MUTED)
    text(fig, .497, .719, "Two valid questions", 16, INK, "bold")
    text(fig, .497, .679, "E+ B+ / singlets", 10, PURPLE, "bold")
    text(fig, .718, .679, "E+ B+ / Expression+", 10, "#458E79", "bold")
    text(fig, .497, .65, "App quadrant % of parent", 9, MUTED)
    text(fig, .718, .65, "Derived conditional binding fraction", 9, MUTED)
    ax = fig.add_axes([.57, .29, .333, .315])
    y = np.arange(3)
    fractions = [next(p["percent_parent"] for p in row["populations"] if p["name"] == "Demo E+ B+") for row in rows]
    conditional = [r["binding_positive_percent_of_expression_positive"] for r in rows]
    for offset, values, color in [(.17, fractions, PURPLE), (-.17, conditional, MINT)]:
        ax.barh(y + offset, values, height=.26, color=color, zorder=3)
        for pos, value in zip(y + offset, values):
            ax.text(value + 1.2, pos, f"{value:.2f}%", va="center", color=INK, fontsize=9, weight="bold")
    ax.set_yticks(y, [f"{name} demo" for name in SAMPLE_NAMES])
    ax.invert_yaxis()
    ax.set_xlim(0, 85)
    ax.set_xticks([0, 20, 40, 60, 80], ["0%", "20%", "40%", "60%", "80%"])
    ax.grid(axis="x", color=LINE, zorder=0)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, pad=12)
    ax.set_xlabel("Same numerator, different reference population", fontsize=9, labelpad=9)
    text(fig, .497, .205, "Expression+ overlaps E+ B− and E+ B+. Do not add it to the four quadrants.", 9, MUTED)
    footer(fig, "Synthetic results · conditional fractions are calculated from exported counts · no biological replicates are simulated")
    save(fig, "denominators")


def write_reference(engine, infos, rows):
    project = {
        "format": "aureka-flow-project", "schema_version": 1,
        "software": {"aureka_flow": __version__, "flowkit": fk.__version__},
        "samples": [{k: i[k] for k in ("filename", "sha256", "events", "origin")} for i in infos],
        "gates": [g.model_dump() for g in engine.gates],
        "notes": "SYNTHETIC tutorial template. Click Try synthetic demo data before Open project. "
                 "No experimental files are embedded. Demo thresholds and scatter/singlet geometry are illustrative; "
                 "they are not validated gates for real yeast-display experiments.",
    }
    (DOCS / "tutorial-project.json").write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n")
    (ASSETS / "tutorial-project.json").write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n")
    metrics = {"description": "SYNTHETIC full-event tutorial reference, not experimental measurements",
               "software": project["software"], "samples": rows}
    (DOCS / "tutorial-metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    (ASSETS / "tutorial-metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    table = ["# Synthetic demo reference results", "", "Generated by `python scripts/build_tutorial.py` from the application's seeded demo. "
             "All counts use full event data. These samples are not biological replicates or experimental controls.", "",
             "| Sample | All events | Demo cells | Demo singlets | Expression+ | E+ B+ | E+ B+ / singlets | E+ B+ / Expression+ | Median binding in E+ (Logicle) |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        p = {p["name"]: p for p in row["populations"]}
        counts = [p[n]["count"] for n in ("root", "Demo cells", "Demo singlets", "Demo Expression+", "Demo E+ B+")]
        table.append(f"| {row['sample']} | " + " | ".join(f"{n:,}" for n in counts) +
                     f" | {p['Demo E+ B+']['percent_parent']:.2f}% | {row['binding_positive_percent_of_expression_positive']:.2f}%"
                     f" | {row['median_binding_logicle_in_expression_positive']:.6f} |")
    table += ["", "The first percentage is the app's quadrant **% of parent**; the second is a derived ratio of two population counts. "
              "They answer different questions. See the [tutorial](TUTORIAL.md#read-the-results-with-the-right-denominator).", "",
              "## All saved populations", "", "| Sample | Population | Parent | Count | % of parent | % of all events |",
              "| --- | --- | --- | ---: | ---: | ---: |"]
    for row in rows:
        for p in row["populations"]:
            table.append(f"| {row['sample']} | {p['name']} | {p['parent'] or '—'} | {p['count']:,} | "
                         f"{p['percent_parent']:.6f}% | {p['percent_total']:.6f}% |")
    table += ["", "Machine-readable results and source SHA-256 hashes: [tutorial-metrics.json](tutorial-metrics.json).", "",
              "Exact reusable gate template: [tutorial-project.json](tutorial-project.json).", ""]
    (DOCS / "DEMO_RESULTS.md").write_text("\n".join(table))


GUIDE_CSS = """
:root{--purple:#4200ac;--mint:#6fc0a9;--ink:#33266c;--muted:#77718b;--line:#e6e1ef;--bg:#f7f6fb}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:85px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
a{color:var(--purple);text-underline-offset:3px}header{position:sticky;top:0;z-index:4;background:#fffffff2;backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.header-inner{max-width:1200px;margin:auto;padding:17px 28px;display:flex;align-items:center;justify-content:space-between;gap:20px}.logo{display:flex;align-items:center;gap:13px;text-decoration:none;font-size:13px;font-weight:700;letter-spacing:2px}.logo img{width:119px;height:auto}.header-links{display:flex;gap:23px;font-size:13px;font-weight:600}
main{max-width:1200px;margin:auto;display:grid;grid-template-columns:230px minmax(0,1fr);gap:44px;padding:30px 28px 75px}aside{position:sticky;top:96px;align-self:start;max-height:calc(100vh - 120px);overflow:auto;font-size:12px;line-height:1.5}aside strong{display:block;font-size:10px;letter-spacing:1.4px;margin:5px 0 13px;color:var(--muted)}aside ul{list-style:none;padding-left:0}aside li{margin:10px 0}aside a{text-decoration:none;color:var(--muted)}aside a:hover{color:var(--purple)}aside li ul{padding-left:13px;font-size:11px}aside li ul li{margin:7px 0}
article{min-width:0;background:white;border:1px solid var(--line);border-radius:20px;padding:38px 42px;box-shadow:0 8px 40px #33266c04}h1{font-size:38px;line-height:1.2;letter-spacing:-1.2px;margin:0 0 18px}h2{font-size:26px;line-height:1.3;letter-spacing:-.5px;margin:54px 0 18px;border-top:1px solid var(--line);padding-top:30px}h3{font-size:19px;margin:30px 0 10px}h4{font-size:16px;margin:24px 0 8px}p{margin:13px 0}li{margin:8px 0}img{max-width:100%;height:auto}article img{display:block;border-radius:10px;margin:24px auto;border:1px solid var(--line)}blockquote{margin:22px 0;padding:12px 20px;border-left:4px solid var(--mint);background:#f0f8f5;border-radius:0 9px 9px 0}blockquote p{margin:4px 0}pre{overflow-x:auto;background:#241245;color:#f7f6fb;padding:20px;border-radius:10px;font-size:12px;line-height:1.7}code{font:0.86em/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;background:#f1edf8;padding:2px 5px;border-radius:4px}pre code{background:none;padding:0;font-size:inherit;color:inherit}table{border-collapse:collapse;width:100%;font-size:12px;line-height:1.6;display:block;overflow-x:auto;margin:20px 0}th,td{padding:11px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--bg);color:var(--purple)}.badge{display:inline-block;background:#ede6f8;color:var(--purple);font-size:10px;font-weight:700;letter-spacing:1px;padding:5px 10px;border-radius:20px;margin-bottom:15px}footer{max-width:1200px;margin:auto;padding:0 28px 35px;color:var(--muted);font-size:12px}
.learning-path{margin:30px 0;padding:20px;background:var(--bg);border:1px solid var(--line);border-radius:14px}.learning-label{font-size:10px;font-weight:700;letter-spacing:1.3px;color:var(--muted);margin:0 0 13px}.lesson-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.lesson{display:block;text-decoration:none;background:white;border:1px solid var(--line);border-radius:8px;padding:12px;line-height:1.5}.lesson:hover{border-color:var(--purple);box-shadow:0 3px 12px #4200ac08}.lesson span{font-size:10px;color:var(--purple);font-weight:700;display:block;margin-bottom:5px}.lesson b{font-size:12px;color:var(--ink)}.learning-path>p:last-child{font-size:12px;margin:13px 0 0}
@media(max-width:900px){main{grid-template-columns:1fr;padding:20px 16px 50px;gap:15px}aside{position:static;max-height:none;background:white;padding:16px 22px;border:1px solid var(--line);border-radius:12px}aside ul{columns:2}aside li ul{display:none}article{padding:27px 22px}h1{font-size:32px}.header-inner{padding:15px 18px}.header-links{gap:15px;font-size:12px}}
@media(max-width:500px){body{font-size:14px}aside ul{columns:1}.header-links a:first-child{display:none}.logo img{width:94px}h2{font-size:23px}h1{font-size:29px}article{padding:23px 18px}th,td{padding:9px}}
@media(max-width:600px){.lesson-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.learning-path{padding:14px}}
@media print{header,aside{display:none}main{display:block;padding:0}article{border:0;padding:0;box-shadow:none}body{font-size:11px;background:white}h2{break-before:auto}img,table,pre,blockquote{break-inside:avoid}h1,h2,h3{break-after:avoid}a{color:var(--ink)}footer{display:none}}
"""


def render_guide():
    source = (DOCS / "TUTORIAL.md").read_text()
    source = source.replace("../aureka_flow/static/assets/", "assets/")
    repo_docs = "https://github.com/Drjackxiaoyuchen/aureka-flow/blob/main/docs/"
    for name in ("tutorial-project.json", "tutorial-metrics.json"):
        source = source.replace(f"]({name})", f"](assets/{name})")
    for name in ("DEMO_RESULTS.md",):
        source = source.replace(f"]({name})", f"]({repo_docs}{name})")
    source = source.replace("](../README.md", "](https://github.com/Drjackxiaoyuchen/aureka-flow/blob/main/README.md")
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc"], extension_configs={"toc": {"toc_depth": "2-3"}})
    body = md.convert(source)
    body = body.replace('href="assets/tutorial-project.json"', 'href="assets/tutorial-project.json" download="tutorial-project.json"')
    lessons = [("01", "Open & inspect", "understand-the-workspace"),
               ("02", "Scale & compensate", "3-assign-expression-and-binding-channels"),
               ("03", "Build a hierarchy", "rebuild-the-demo-gates-by-hand"),
               ("04", "Expression × binding", "4-create-quadrants-and-expression"),
               ("05", "Compare & interpret", "compare-distributions-and-medians"),
               ("06", "Save & reproduce", "save-a-reproducible-analysis")]
    cards = "".join(f'<a class="lesson" href="#{anchor}"><span>PART {number}</span><b>{title}</b></a>'
                    for number, title, anchor in lessons)
    learning = f'<section class="learning-path" aria-label="Six-part learning path"><p class="learning-label">SIX-PART LEARNING PATH</p><div class="lesson-grid">{cards}</div><p>New here? <a href="#start-here">Try the ten-minute demo first →</a></p></section>'
    body = body.replace('<h2 id="start-here">', learning + '\n<h2 id="start-here">', 1)
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aureka Flow · User & analysis guide</title><meta name="theme-color" content="#4200ac"><style>{GUIDE_CSS}</style></head>
<body><header><div class="header-inner"><a class="logo" href="/"><img src="assets/aureka-logo.png" alt="aureka"><span>FLOW</span></a>
<nav class="header-links"><a href="/">Open workspace</a><a href="https://github.com/Drjackxiaoyuchen/aureka-flow" target="_blank" rel="noreferrer">GitHub ↗</a></nav></div></header>
<main><aside aria-label="Guide contents"><strong>USER & ANALYSIS GUIDE</strong>{md.toc}</aside><article><span class="badge">AUREKA FLOW v0.1 · SYNTHETIC WORKED EXAMPLE</span>{body}</article></main>
<footer>Guide and figures are included locally. Repository and reference links open external pages. No experimental FCS files are included.</footer></body></html>
'''
    (ROOT / "aureka_flow/static/guide.html").write_text(html)


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    engine, infos, rows, comparison, expr, bind = analyze()
    write_reference(engine, infos, rows)
    overview(engine, infos, rows, comparison, expr, bind)
    gating(engine, infos, rows, comparison, expr, bind)
    denominators(rows)
    render_guide()
    print("Built 3 SVG/PNG figures, synthetic project/results and local HTML guide.")


if __name__ == "__main__":
    main()
