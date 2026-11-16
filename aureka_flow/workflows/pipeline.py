"""Connect original components without sharing checkout paths or private data."""
from __future__ import annotations

from aureka_flow import __version__

from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path

from aureka_flow.workflows.core.core import analyze_fcs, demo as measurement_demo
from aureka_flow.workflows.workbench.analysis import analyze, synthetic_manifest
from aureka_flow.workflows.workbench.cli import write_output
from aureka_flow.workflows.workbench.validation import read_json
from aureka_flow.workflows.sortseq.cli import dump, report as sortseq_report
from aureka_flow.workflows.sortseq.linkage import link_experiment, synthetic_inputs

MODULES = [
    ("ingest", "Data and sample mapping", "FCS provenance and explicit sample identities"),
    ("qc", "Acquisition QC", "Time consistency, non-finite values and reviewed external masks"),
    ("gating", "Compensation and gating", "Declared processing and explicit selected-event denominators"),
    ("experiment", "Experiment and batch comparisons", "Metadata joins, replicate checks and cross-batch restrictions"),
    ("report", "Visualization and reporting", "Descriptive marker summaries and auditable warnings"),
    ("sortseq", "Sort-seq bridge", "Sort-bin to decoded-count linkage; no affinity inference"),
]


def new_output(path):
    path=Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError("output must be a fresh nonexistent directory")
    return path


def strict_keys(value, required, optional, field):
    if not isinstance(value,dict): raise ValueError(f"{field} must be an object")
    if set(value)-set(required)-set(optional): raise ValueError(f"{field} has unknown fields")
    if set(required)-set(value): raise ValueError(f"{field} is missing required fields")


def file_path(value, base, field):
    if not isinstance(value,str) or not value.strip(): raise ValueError(f"{field} must name an input file")
    p=Path(value).expanduser()
    p=p if p.is_absolute() else base/p
    if not p.is_file(): raise ValueError(f"{field}: input file not found")
    return p


def collect_run(run_file):
    """Compute all inputs first; do not create outputs for an invalid run."""
    run_file=Path(run_file)
    spec=read_json(run_file)
    strict_keys(spec,["schema_version","files","sample_manifest"],["sort_bins","variant_counts"],"run")
    if spec["schema_version"]!="yeast-facs-run/v1": raise ValueError("run.schema_version must be yeast-facs-run/v1")
    files=spec["files"]
    if not isinstance(files,list) or not files: raise ValueError("run.files must be a nonempty array")
    if ("sort_bins" in spec)!=("variant_counts" in spec): raise ValueError("sort_bins and variant_counts must be supplied together")
    base=run_file.parent
    manifest=read_json(file_path(spec["sample_manifest"],base,"sample_manifest"))
    samples=[]; kinds=set(); resolved=set(); hashes=set()
    for i, record in enumerate(files):
        strict_keys(record,["fcs","config"],["qc_mask"],f"run.files[{i}]")
        fcs=file_path(record["fcs"],base,f"files[{i}].fcs")
        if fcs.resolve() in resolved: raise ValueError("same FCS path supplied more than once")
        resolved.add(fcs.resolve())
        config=read_json(file_path(record["config"],base,f"files[{i}].config"))
        if "qc_mask" in record:
            mask=read_json(file_path(record["qc_mask"],base,f"files[{i}].qc_mask"))
            measured=analyze_fcs(fcs,config,qc_mask=mask)
        else: measured=analyze_fcs(fcs,config)
        for sample in measured["samples"]:
            digest=sample["source"]["sha256"]
            if digest in hashes: raise ValueError("duplicate FCS content detected; exports are not independent acquisitions")
            hashes.add(digest)
        samples.extend(measured["samples"]); kinds.add(measured["evidence_kind"])
    if len(kinds)!=1: raise ValueError("cannot mix synthetic and user_data acquisitions in one run")
    measurements={"schema_version":"yeast-facs-measurements/v1","evidence_kind":next(iter(kinds)),"samples":samples}
    experiment=analyze(measurements,manifest)
    linked=None; sort_inputs=None
    if "sort_bins" in spec:
        bins=read_json(file_path(spec["sort_bins"],base,"sort_bins"))
        counts=read_json(file_path(spec["variant_counts"],base,"variant_counts"))
        linked=link_experiment(experiment,bins,counts)
        sort_inputs=(bins,counts)
    return measurements,manifest,experiment,linked,sort_inputs


def landing(evidence_kind, has_sortseq, samples):
    cards="".join(f'<li><span>0{i}</span><h2>{html.escape(title)}</h2><p>{html.escape(sub)}</p></li>' for i,(_,title,sub) in enumerate(MODULES,1))
    link='<a href="06-sortseq/report.html">Open sort-seq linkage report →</a>' if has_sortseq else '<span>Sort-seq not run: no sort map/count inputs supplied.</span>'
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'"><title>Aureka Flow · Experiment workflow</title><style>body{margin:0;color:#203936;background:#f3f7f5;font:16px/1.55 system-ui,sans-serif}main{max-width:1050px;padding:52px 28px;margin:auto}h1{font-size:44px;line-height:1.12;font-weight:600;letter-spacing:-.04em}h2{font-size:19px;font-weight:500;margin:8px 0}header>p{max-width:740px}.tag{letter-spacing:.12em;font-size:12px;color:#376e61}ol{padding:0;list-style:none;display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin:38px 0}li{border-top:2px solid #378876;padding-top:14px}li>span{color:#467768}li>p{font-size:14px;color:#536c65}nav{display:flex;flex-wrap:wrap;gap:22px;padding:22px 0;border-top:1px solid #c6d9d1}a{color:#166650}aside{background:#e7efe9;padding:18px 22px;border-left:3px solid #447d67}footer{margin-top:32px;font-size:13px;color:#587067}@media(max-width:650px){ol{grid-template-columns:1fr 1fr}h1{font-size:33px}main{padding:28px 20px}}@media(max-width:390px){ol{grid-template-columns:1fr}}</style></head><body><main><header><p class="tag">OPEN WORKFLOW · SIX CONNECTED MODULES</p><h1>Yeast FACS, from files<br>to traceable evidence.</h1><p>"""+html.escape(evidence_kind.upper())+f""" · {samples} acquisition records. A local, auditable workflow with explicit identities, processing decisions and measurement limits.</p></header><ol>"""+cards+"""</ol><nav><a href="05-report/report.html">Open experiment report →</a>"""+link+"""<a href="run-receipt.json">Run receipt</a></nav><aside><b>Software alpha—not biological validation.</b> Events are not biological replicates. Selected populations are not automatically live singlets. Fluorescence and read fractions are not affinity. Unimplemented upstream integrations are not hidden behind a success label.</aside><footer>No private data is distributed with this project. The synthetic demo is deliberately small; it tests software connections, not assay performance.</footer></main></body></html>"""


def write_run(output, measurements, manifest, experiment, linked, sort_inputs=None, synthetic=False):
    output=new_output(output)
    # Prepare all serializations and HTML before making a directory.
    json.dumps([measurements,manifest,experiment,linked],allow_nan=False)
    page=landing(measurements["evidence_kind"],linked is not None,len(measurements["samples"]))
    sortpage=sortseq_report(linked) if linked is not None else None
    output.mkdir(parents=True,exist_ok=False)
    dump(output/"measurements.json",measurements)
    dump(output/"samples.json",manifest)
    write_output(output/"05-report",experiment)
    if linked is not None:
        directory=output/"06-sortseq"; directory.mkdir()
        dump(directory/"linked_counts.json",linked)
        (directory/"report.html").write_text(sortpage,encoding="utf-8")
        if synthetic and sort_inputs:
            dump(directory/"synthetic_sort_bins.json",sort_inputs[0])
            dump(directory/"synthetic_variant_counts.json",sort_inputs[1])
    (output/"index.html").write_text(page,encoding="utf-8")
    files=sorted(p for p in output.rglob("*") if p.is_file())
    receipt={"schema_version":"yeast-facs-run-receipt/v1","producer":{"name":"aureka-flow","version":__version__,"component":"workflow"},
             "evidence_kind":measurements["evidence_kind"],"sample_records":len(measurements["samples"]),
             "comparison_status":experiment["comparison_status"],
             "modules":[{"id":name,"status":"descriptive_linkage" if name=="sortseq" and linked is not None else "not_run" if name=="sortseq" else "software_demo" if synthetic else "executed"} for name,_,_ in MODULES],
             "files":[{"path":str(p.relative_to(output)),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
             "biological_validation":False,"upstream_integration_scope":"FlowKit native execution; external QC masks; other catalog tools remain references or future adapters"}
    dump(output/"run-receipt.json",receipt)
    return receipt


def demo_run(output):
    new_output(output)
    measurements=measurement_demo()
    manifest=synthetic_manifest(measurements)
    experiment=analyze(measurements,manifest)
    bins,counts=synthetic_inputs(experiment)
    linked=link_experiment(experiment,bins,counts)
    return write_run(output,measurements,manifest,experiment,linked,(bins,counts),synthetic=True)


def run_batch(run_file,output):
    new_output(output)
    result=collect_run(run_file)
    return write_run(output,*result,synthetic=False)
