"""Loopback-only application server; uploaded data stay in process memory."""
import io
import json
from pathlib import Path

import flowkit as fk
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from plotly.offline import get_plotlyjs
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .demo import demo_files
from .engine import AnalysisEngine, ComparisonSpec, GateSpec, MAX_FILE_BYTES, ProjectSpec, QuadrantsSpec, ROOT, ViewSpec

app = FastAPI(title="Aureka Flow", version=__version__)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
engine = AnalysisEngine()
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
VALIDATION_DIR = ROOT / "validation/workspace-report"
if not VALIDATION_DIR.exists() and (ROOT / "validation/human_gating_20261105").exists():
    VALIDATION_DIR = ROOT / "validation/human_gating_20261105"


@app.get("/validation/")
def validation_index():
    generated = VALIDATION_DIR / "index.html"
    return FileResponse(generated if generated.exists() else STATIC / "validation-index.html")


app.mount("/validation", StaticFiles(directory=VALIDATION_DIR, html=True, check_dir=False), name="validation")


@app.exception_handler(ValueError)
async def input_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/vendor/plotly.js")
def plotly_js():
    return Response(get_plotlyjs(), media_type="application/javascript", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/state")
def state():
    with engine.lock:
        return {"version": __version__, "flowkit_version": fk.__version__,
                "samples": [rec.info() for rec in engine.samples.values()],
                "gates": [g.model_dump() for g in engine.gates]}


@app.post("/api/upload")
def upload(files: list[UploadFile] = File(...)):
    if len(files) > 24:
        raise HTTPException(422, "Choose at most 24 FCS files at a time.")
    loaded, errors = [], []
    with engine.lock:
        for file in files:
            try:
                if not (file.filename or "").lower().endswith(".fcs"):
                    raise ValueError("Choose an .fcs file.")
                data = file.file.read(MAX_FILE_BYTES + 1)
                loaded.append(engine.load(data, file.filename))
            except Exception as exc:
                errors.append({"filename": file.filename, "error": str(exc)})
            finally:
                file.file.close()
    return {"samples": loaded, "errors": errors}


@app.post("/api/demo")
def demo():
    with engine.lock:
        loaded = [engine.load(data, name, "Synthetic demo · simulated signals, not experimental data")
                  for name, data in demo_files()]
        return {"samples": loaded}


@app.delete("/api/samples/{sample_id}")
def remove_sample(sample_id: str):
    with engine.lock:
        engine.remove_sample(sample_id)
    return {"removed": sample_id}


@app.post("/api/view")
def view(spec: ViewSpec):
    with engine.lock:
        return engine.view(spec)


@app.post("/api/compare")
def compare(spec: ComparisonSpec):
    with engine.lock:
        return engine.compare(spec)


@app.post("/api/gates")
def add_gate(spec: GateSpec, sample_id: str):
    with engine.lock:
        return engine.add_gate(spec, sample_id)


@app.delete("/api/gates/{name}")
def delete_gate(name: str):
    with engine.lock:
        return {"deleted": engine.delete_gate(name)}


@app.get("/api/project")
def export_project():
    with engine.lock:
        data = json.dumps(engine.project(), indent=2, ensure_ascii=False)
    return Response(data, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="aureka-flow-project.json"'})


@app.post("/api/quadrants")
def quadrants(spec: QuadrantsSpec):
    with engine.lock:
        return engine.add_quadrants(spec)


@app.post("/api/project")
def import_project(project: ProjectSpec):
    with engine.lock:
        engine.set_gates(project.gates)
        hashes = {r.digest for r in engine.samples.values()}
        missing = [r.get("filename", "unknown") for r in project.samples if r.get("sha256") not in hashes]
    return {"gates": len(project.gates), "missing_sources": missing}


@app.get("/api/gatingml")
def gatingml(sample_id: str):
    with engine.lock:
        rec = engine.record(sample_id)
        engine.validate_sample(rec)
        xml, _ = engine.gatingml()
    return Response(xml, media_type="application/xml", headers={"Content-Disposition": 'attachment; filename="aureka-gates.xml"'})


@app.post("/api/export/stats")
def export_stats(spec: ComparisonSpec):
    with engine.lock:
        rows = engine.compare(spec)["rows"]
        csv = pd.DataFrame(rows).to_csv(index=False)
    return Response(csv, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="aureka-population-statistics.csv"'})


@app.post("/api/export/events")
def export_events(spec: ViewSpec):
    with engine.lock:
        rec = engine.record(spec.sample_id)
        mask = engine.mask(rec, spec.population)
        events = engine.events(rec, spec.compensation)[mask]
        df = pd.DataFrame(events, columns=rec.sample.pnn_labels)
        import numpy as np
        df.insert(0, "event_index_zero_based", np.flatnonzero(mask))
        df.insert(0, "source_sha256", rec.digest)
        df.insert(0, "source_filename", rec.filename)
        df.insert(0, "compensation", spec.compensation)
        df.insert(0, "population", spec.population)
        csv = df.to_csv(index=False)
    return Response(csv, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="aureka-gated-events.csv"'})


@app.get("/api/metadata/{sample_id}")
def metadata(sample_id: str):
    with engine.lock:
        rec = engine.record(sample_id)
        return {"sample": rec.info(), "fcs_metadata": rec.sample.get_metadata(),
                "spillover_matrix": rec.sample.compensation.matrix.tolist() if rec.sample.compensation else None,
                "spillover_detectors": rec.sample.compensation.detectors if rec.sample.compensation else []}
