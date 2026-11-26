"""Browser workspace service; each opaque cookie owns a separate FlowKit engine."""
import hashlib
import io
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import zipfile

import flowkit as fk
import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from plotly.offline import get_plotlyjs
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, config
from .demo import demo_files
from .engine import ComparisonSpec, GateEditSpec, GateRevisionSpec, GateSpec, ProjectSpec, QuadrantsSpec, ROOT, ViewSpec
from .sessions import ServerBusy, SessionStore
from .request_limits import RequestBodyLimit
from .archive_intake import fcs_archive, read_member
from .bd_workspace import DivaWorkspace, MAX_XML_BYTES
from .workflows.browser import ExperimentSpec, acquisition_qc, experiment_inputs, manifest_template
from .workflows.pipeline import write_run

app = FastAPI(title="Aureka Flow", version=__version__)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
app.add_middleware(RequestBodyLimit)
sessions = SessionStore()
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
VALIDATION_DIR = ROOT / "validation/workspace-report"
if not VALIDATION_DIR.exists() and (ROOT / "validation/human_gating_20261105").exists():
    VALIDATION_DIR = ROOT / "validation/human_gating_20261105"


@app.middleware("http")
async def browser_workspace(request: Request, call_next):
    if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
        response = await call_next(request)
        if request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (
            origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()
        ):
            return JSONResponse({"detail": "Open the app on its own server address to submit analysis requests."}, status_code=403)
    cookie = f"aureka_flow_{request.url.port or 'web'}"
    try:
        token, workspace = sessions.acquire(request.cookies.get(cookie))
    except ServerBusy as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": "60"})
    request.state.workspace = workspace
    try:
        response = await call_next(request)
        response.set_cookie(cookie, token, max_age=sessions.ttl, httponly=True, samesite="lax",
                            secure=config.SECURE_COOKIES or request.url.scheme == "https")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    finally:
        sessions.release(workspace)


def engine_for(request):
    return request.state.workspace.engine


@app.exception_handler(ValueError)
async def input_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/validation/")
def validation_index():
    generated = VALIDATION_DIR / "index.html"
    return FileResponse(generated if not config.SERVER_MODE and generated.exists() else STATIC / "validation-index.html")


if not config.SERVER_MODE:
    app.mount("/validation", StaticFiles(directory=VALIDATION_DIR, html=True, check_dir=False), name="validation")


@app.get("/vendor/plotly.js")
def plotly_js():
    return Response(get_plotlyjs(), media_type="application/javascript", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "mode": "server" if config.SERVER_MODE else "local"}


@app.get("/api/state")
def state(request: Request):
    engine = engine_for(request)
    with engine.lock:
        return {"version": __version__, "flowkit_version": fk.__version__,
                "capabilities": {"plot_types": ["scatter", "histogram"], "range_gates": True,
                                 "backgating": True, "histogram_overlays": True, "population_table": True,
                                 "experiment_reports": True, "acquisition_qc": True, "bd_xml_import": True,
                                 "gate_editing": True, "boolean_gates": True},
                "workspace": {"id": request.state.workspace.public_id, "mode": "server" if config.SERVER_MODE else "local",
                              "idle_timeout_seconds": sessions.ttl},
                "limits": {"file_bytes": config.MAX_FILE_BYTES, "session_bytes": config.MAX_TOTAL_BYTES, "samples": 24},
                "samples": [rec.info() for rec in engine.samples.values()],
                "gates": [g.model_dump() for g in engine.gates],
                "gate_history": engine.gate_history(),
                "imported_workspace": ({"filename": engine.workspace["source"]["filename"],
                                        "sha256": engine.workspace["source"]["sha256"],
                                        "mode": engine.workspace["mode"], "worksheet": engine.workspace["worksheet"],
                                        "note": engine.workspace["reconstruction_note"]} if engine.workspace else None)}


def load_bytes(request, data, filename, origin="uploaded FCS"):
    workspace, engine = request.state.workspace, engine_for(request)
    digest = hashlib.sha256(data).hexdigest()
    for record in engine.samples.values():
        if record.digest == digest:
            return record.info()
    sessions.reserve(workspace, len(data))
    added = 0
    try:
        info = engine.load(data, filename, origin)
        added = info["size_bytes"]
        return info
    finally:
        sessions.commit(workspace, len(data), added)


@app.post("/api/upload")
def upload(request: Request, files: list[UploadFile] = File(...)):
    if len(files) > 24:
        raise HTTPException(422, "Choose at most 24 files or archives at a time.")
    engine = engine_for(request)
    loaded, errors, skipped = [], [], []
    expanded_bytes = 0
    with engine.lock:
        for file in files:
            try:
                name = Path((file.filename or "").replace("\\", "/")).name
                if not name.lower().endswith((".fcs", ".zip")):
                    raise ValueError("Choose an .fcs file or an FCS .zip archive.")
                data = file.file.read(config.MAX_FILE_BYTES + 1)
                if len(data) > config.MAX_FILE_BYTES:
                    raise ValueError("The uploaded file or archive exceeds the per-file upload limit.")
                if name.lower().endswith(".zip"):
                    with fcs_archive(data, file_limit=config.MAX_FILE_BYTES,
                                     expanded_limit=config.MAX_TOTAL_BYTES - expanded_bytes) as (archive, members, ignored):
                        archive_digest = hashlib.sha256(data).hexdigest()
                        expanded_bytes += sum(member.file_size for member in members)
                        skipped.extend({"filename": name, **item} for item in ignored)
                        for member in members:
                            path = member.orig_filename.replace("\\", "/")
                            try:
                                member_data = read_member(archive, member, config.MAX_FILE_BYTES)
                                container = {"filename": name, "sha256": archive_digest, "member_path": path,
                                             "member_crc32": f"{member.CRC:08x}"}
                                digest = hashlib.sha256(member_data).hexdigest()
                                existing = next((rec for rec in engine.samples.values() if rec.digest == digest), None)
                                if existing and container not in existing.source_containers and len(existing.source_containers) >= 24:
                                    raise ValueError("Sample provenance limit: 24 distinct archive memberships.")
                                info = load_bytes(request, member_data, path, f"FCS archive · {name} / {path}")
                                rec = engine.record(info["id"])
                                if container not in rec.source_containers:
                                    rec.source_containers.append(container)
                                loaded.append(rec.info())
                            except Exception as exc:
                                errors.append({"filename": f"{name} / {path}", "error": str(exc)})
                else:
                    expanded_bytes += len(data)
                    if expanded_bytes > config.MAX_TOTAL_BYTES:
                        raise ValueError("Expanded FCS data exceed the request budget. Choose a smaller batch.")
                    loaded.append(load_bytes(request, data, name))
            except Exception as exc:
                errors.append({"filename": file.filename, "error": str(exc)})
            finally:
                file.file.close()
    return {"samples": loaded, "errors": errors, "skipped": skipped}


@app.post("/api/demo")
def demo(request: Request):
    engine = engine_for(request)
    with engine.lock:
        loaded = [load_bytes(request, data, name, "Synthetic demo · simulated signals, not experimental data")
                  for name, data in demo_files()]
        return {"samples": loaded}


@app.delete("/api/samples/{sample_id}")
def remove_sample(sample_id: str, request: Request):
    engine = engine_for(request)
    with engine.lock:
        size = engine.record(sample_id).size
        engine.remove_sample(sample_id)
        sessions.subtract(request.state.workspace, size)
    return {"removed": sample_id}


@app.delete("/api/session")
def clear_workspace(request: Request):
    engine = engine_for(request)
    with engine.lock:
        size = sum(r.size for r in engine.samples.values())
        if engine.workspace:
            size += len(DivaWorkspace.from_source(engine.workspace["source"]).data)
        engine.samples.clear()
        engine.workspace = None
        engine.set_gates([])
        sessions.subtract(request.state.workspace, size)
    return {"cleared": True}


@app.post("/api/view")
def view(spec: ViewSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return engine.view(spec)


@app.post("/api/compare")
def compare(spec: ComparisonSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return engine.compare(spec)


@app.post("/api/gates")
def add_gate(spec: GateSpec, sample_id: str, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return engine.add_gate(spec, sample_id)


@app.delete("/api/gates/{name}")
def delete_gate(name: str, request: Request, revision: int | None = None):
    engine = engine_for(request)
    with engine.lock:
        return {"deleted": engine.delete_gate(name, revision)}


@app.put("/api/gates/{name}")
def edit_gate(name: str, spec: GateEditSpec, sample_id: str, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return engine.edit_gate(name, spec, sample_id)


@app.post("/api/gate-history/{direction}")
def gate_history(direction: str, spec: GateRevisionSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return engine.navigate_gate_history(direction, spec.revision)


@app.get("/api/project")
def export_project(request: Request):
    engine = engine_for(request)
    with engine.lock:
        data = json.dumps(engine.project(), indent=2, ensure_ascii=False)
    return Response(data, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="aureka-flow-project.json"'})


@app.post("/api/quadrants")
def quadrants(spec: QuadrantsSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return engine.add_quadrants(spec)


@app.post("/api/project")
def import_project(project: ProjectSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        doc = DivaWorkspace.from_source(project.workspace["source"]) if project.workspace else None
        old_size = len(DivaWorkspace.from_source(engine.workspace["source"]).data) if engine.workspace else 0
        reservation = len(doc.data) if doc else 0
        sessions.reserve(request.state.workspace, reservation)
        try:
            engine.restore_project(project)
        except Exception:
            sessions.commit(request.state.workspace, reservation, 0)
            raise
        sessions.commit(request.state.workspace, reservation, reservation - old_size)
        hashes = {r.digest for r in engine.samples.values()}
        missing = [r.get("filename", "unknown") for r in project.samples if r.get("sha256") not in hashes]
    return {"gates": len(project.gates), "missing_sources": missing}


def read_workspace(file):
    return DivaWorkspace(file.file.read(MAX_XML_BYTES + 1), file.filename or "experiment.xml")


@app.post("/api/workspace/xml/preview")
def preview_workspace(request: Request, file: UploadFile = File(...)):
    doc = read_workspace(file)
    result = doc.preview()
    with engine_for(request).lock:
        result["matches"], result["errors"] = [], []
        for rec in engine_for(request).samples.values():
            try:
                index = doc.match(rec)
                result["matches"].append({"filename": rec.filename, "sha256": rec.digest, "xml_sample_index": index})
            except ValueError as exc:
                result["errors"].append(str(exc))
    return result


@app.post("/api/workspace/xml")
def import_workspace(request: Request, file: UploadFile = File(...), worksheet: str = Form(...),
                     mode: str = Form("preserve"), compensation: str = Form("raw"),
                     acknowledged: bool = Form(False)):
    doc, engine = read_workspace(file), engine_for(request)
    with engine.lock:
        old_size = len(DivaWorkspace.from_source(engine.workspace["source"]).data) if engine.workspace else 0
        sessions.reserve(request.state.workspace, len(doc.data))
        try:
            engine.import_workspace(doc, worksheet, mode, compensation, acknowledged)
        except Exception:
            sessions.commit(request.state.workspace, len(doc.data), 0)
            raise
        sessions.commit(request.state.workspace, len(doc.data), len(doc.data) - old_size)
        return {"gates": len(engine.gates), "mode": mode, "sha256": doc.sha256,
                "matched_samples": len(engine.workspace["bindings"])}


@app.get("/api/workspace/xml")
def export_workspace(request: Request):
    engine = engine_for(request)
    with engine.lock:
        if not engine.workspace:
            raise ValueError("No preserved XML workspace in this browser session.")
        doc = DivaWorkspace.from_source(engine.workspace["source"])
    return Response(doc.data, media_type="application/xml",
                    headers={"Content-Disposition": 'attachment; filename="source-workspace.xml"'})


@app.get("/api/gatingml")
def gatingml(sample_id: str, request: Request):
    engine = engine_for(request)
    with engine.lock:
        engine.validate_sample(engine.record(sample_id))
        xml, _ = engine.gatingml(engine.record(sample_id))
    return Response(xml, media_type="application/xml", headers={"Content-Disposition": 'attachment; filename="aureka-gates.xml"'})


@app.post("/api/export/stats")
def export_stats(spec: ComparisonSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        csv = pd.DataFrame(engine.compare(spec)["rows"]).to_csv(index=False)
    return Response(csv, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="aureka-population-statistics.csv"'})


@app.post("/api/population-table")
def population_table(spec: ComparisonSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return engine.population_table(spec)


@app.post("/api/export/population-table")
def export_population_table(spec: ComparisonSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        csv = pd.DataFrame(engine.population_table(spec)["rows"]).to_csv(index=False)
    return Response(csv, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="aureka-all-populations.csv"'})


def write_events(handle, engine, rec, population, compensation):
    indices = np.flatnonzero(engine.mask(rec, population))
    events = engine.events(rec, compensation)
    for start in range(0, max(1, len(indices)), 5000):
        chunk = indices[start:start + 5000]
        frame = pd.DataFrame(events[chunk], columns=rec.sample.pnn_labels)
        frame.insert(0, "event_index_zero_based", chunk)
        frame.insert(0, "source_sha256", rec.digest)
        frame.insert(0, "source_filename", rec.filename)
        frame.insert(0, "compensation", compensation)
        frame.insert(0, "population", population)
        frame.to_csv(handle, index=False, header=start == 0)


def download_file(path, filename, media_type):
    return FileResponse(path, filename=filename, media_type=media_type, background=BackgroundTask(path.unlink, missing_ok=True))


@app.post("/api/export/events")
def export_events(spec: ViewSpec, request: Request):
    engine = engine_for(request)
    path = None
    try:
        with engine.lock, tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False) as handle:
            path = Path(handle.name)
            write_events(handle, engine, engine.record(spec.sample_id), spec.population, spec.compensation)
        return download_file(path, "aureka-gated-events.csv", "text/csv")
    except BaseException:
        if path:
            path.unlink(missing_ok=True)
        raise


@app.post("/api/export/bundle")
def export_bundle(spec: ComparisonSpec, request: Request, include_events: bool = True, include_population_table: bool = False):
    engine = engine_for(request)
    path = None
    try:
        with engine.lock:
            rows = engine.compare(spec)["rows"]
            errors = [f"{r['sample']}: {r['error']}" for r in rows if r.get("error")]
            if errors:
                raise ValueError("Resolve incompatible samples before downloading: " + "; ".join(errors))
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
                path = Path(handle.name)
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
                archive.writestr("project.json", json.dumps(engine.project(), indent=2, ensure_ascii=False))
                archive.writestr("population-statistics.csv", pd.DataFrame(rows).to_csv(index=False))
                if include_population_table:
                    archive.writestr("all-populations.csv", pd.DataFrame(engine.population_table(spec)["rows"]).to_csv(index=False))
                mapping = {}
                gatingml_files = []
                if engine.gates:
                    per_sample = any(g.compensation == "xml" for g in engine.gates)
                    ids = spec.sample_ids if per_sample else spec.sample_ids[:1]
                    for i, uid in enumerate(ids, 1):
                        xml, mapping = engine.gatingml(engine.record(uid))
                        name = f"gates/sample-{i:02d}.xml" if per_sample else "gates.xml"
                        archive.writestr(name, xml)
                        gatingml_files.append({"path": name, "sample_sha256": engine.record(uid).digest})
                if engine.workspace:
                    archive.writestr("source-workspace.xml", DivaWorkspace.from_source(engine.workspace["source"]).data)
                archive.writestr("manifest.json", json.dumps({"population": spec.population, "analysis": spec.model_dump(),
                    "sources": [engine.record(uid).info() for uid in spec.sample_ids], "gate_id_mapping": mapping,
                    "events_included": include_events, "all_populations_included": include_population_table,
                    "gatingml_included": bool(engine.gates),
                    "gatingml_files": gatingml_files,
                    "source_workspace_included": bool(engine.workspace),
                    "software": engine.project()["software"]}, indent=2, ensure_ascii=False))
                archive.writestr("README.txt", "Aureka Flow analysis download\n\n"
                    "Statistics use all gated events. Medians use the chosen display transforms.\n"
                    "Event CSVs retain source or additionally compensated channel values, without display transforms.\n"
                    "Original event indices are zero-based. Source hashes identify the FCS inputs.\n"
                    "Project JSON does not embed the FCS files. Keep the original sources.\n"
                    "GatingML is included only when saved gates exist; check gatingml_files in manifest.json.\n"
                    "XML-compensated strategies have per-sample GatingML matrices. Preserved source-workspace.xml is the original export.\n"
                    "The selected population and its saved parent determine the denominators.\n"
                    "If present, all-populations.csv includes every saved population; event CSVs use only the selected population.\n"
                    "Fluorescence does not establish affinity or cellular potency.\n")
                if include_events:
                    for i, uid in enumerate(spec.sample_ids, 1):
                        rec = engine.record(uid)
                        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(rec.filename).stem)[:80] or "sample"
                        with archive.open(f"events/{i:02d}_{stem}.csv", "w") as destination:
                            with io.TextIOWrapper(destination, encoding="utf-8", newline="") as text:
                                write_events(text, engine, rec, spec.population, spec.compensation)
        return download_file(path, "aureka-analysis.zip", "application/zip")
    except BaseException:
        if path:
            path.unlink(missing_ok=True)
        raise


@app.get("/api/metadata/{sample_id}")
def metadata(sample_id: str, request: Request):
    engine = engine_for(request)
    with engine.lock:
        rec = engine.record(sample_id)
        return {"sample": rec.info(), "fcs_metadata": rec.sample.get_metadata(),
                "spillover_matrix": rec.sample.compensation.matrix.tolist() if rec.sample.compensation else None,
                "spillover_detectors": rec.sample.compensation.detectors if rec.sample.compensation else [],
                "xml_spillover_matrix": rec.xml_compensation.matrix.tolist() if rec.xml_compensation else None,
                "xml_detectors": rec.xml_compensation.detectors if rec.xml_compensation else [],
                "workspace": ({"source_filename": engine.workspace["source"]["filename"],
                               "source_sha256": engine.workspace["source"]["sha256"],
                               "xml_sample_index": engine.workspace["bindings"].get(rec.digest),
                               "mode": engine.workspace["mode"], "note": engine.workspace["reconstruction_note"]}
                              if engine.workspace else None)}


@app.get("/api/qc/{sample_id}")
def sample_qc(sample_id: str, request: Request):
    engine = engine_for(request)
    with engine.lock:
        return acquisition_qc(engine.record(sample_id))


@app.post("/api/experiment-template")
def experiment_template(spec: ComparisonSpec, request: Request):
    engine = engine_for(request)
    with engine.lock:
        data = manifest_template(engine, spec)
    return Response(json.dumps(data, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="aureka-sample-manifest.json"'})


@app.post("/api/export/experiment")
def export_experiment(spec: ExperimentSpec, request: Request):
    engine = engine_for(request)
    path = None
    try:
        with engine.lock, tempfile.TemporaryDirectory() as directory:
            measurements, manifest, experiment = experiment_inputs(engine, spec.analysis, spec.manifest)
            output = Path(directory) / "report"
            receipt = write_run(output, measurements, manifest, experiment, None)
            # The browser engine already performed gating. The receipt must not
            # imply the CLI rectangle adapter or external QC masks ran here.
            receipt["producer"] = {"name": "aureka-flow", "version": __version__}
            receipt["execution_path"] = "browser_saved_population"
            receipt["modules"] = [{"id": item["id"], "status": "not_run" if item["id"] == "sortseq" else "executed"}
                                  for item in receipt["modules"]]
            (output / "project.json").write_text(json.dumps(engine.project(), indent=2), encoding="utf-8")
            receipt["files"].append({"path": "project.json", "sha256": hashlib.sha256((output / "project.json").read_bytes()).hexdigest()})
            (output / "run-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
                path = Path(handle.name)
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for item in sorted(output.rglob("*")):
                    if item.is_file():
                        archive.write(item, item.relative_to(output))
        return download_file(path, "aureka-experiment-report.zip", "application/zip")
    except BaseException:
        if path:
            path.unlink(missing_ok=True)
        raise
