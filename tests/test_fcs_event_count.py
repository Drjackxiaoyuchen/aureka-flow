"""Independently packed FCS fixtures; no instrument compatibility claim."""
import csv
import hashlib
import io
import json
import struct
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from aureka_flow import server
from aureka_flow.engine import AnalysisEngine
from aureka_flow.fcs_import import load_fcs_sample
from aureka_flow.sessions import SessionStore
from aureka_flow.workflows.core.cli import main as core_main
from aureka_flow.workflows.core.core import analyze_fcs, inspect_fcs


NAMES = ["FITC-A", "APC-A", "Time"]
EVENTS = [[30, 6, 8], [10, 2, 1], [20, 4, 4]]


def fcs(*, declared=3, version="3.1", endian="<", kind="F", bits=None, values=None):
    """Pack HEADER/TEXT and DATA directly; never use the reader's writer."""
    formats = {"F": "f", "D": "d", "I": "H"}
    widths = bits or ([64] * 3 if kind == "D" else [16] * 3 if kind == "I" else [32] * 3)
    values = [v for row in EVENTS for v in row] if values is None else values
    data = b"".join(struct.pack(endian + ("I" if kind == "I" and widths[i % 3] == 32
                                         else formats[kind]), value)
                    for i, value in enumerate(values))
    begin, end = 4096, 4096 + len(data) - 1
    pairs = [("$BYTEORD", "1,2,3,4" if endian == "<" else "4,3,2,1"),
             ("$DATATYPE", kind), ("$MODE", "L"), ("$PAR", "3"), ("$TOT", str(declared)),
             ("$BEGINDATA", str(begin)), ("$ENDDATA", str(end)), ("$NEXTDATA", "0")]
    for i, name in enumerate(NAMES, 1):
        pairs += [(f"$P{i}N", name), (f"$P{i}B", str(widths[i-1])), (f"$P{i}R", "1024"),
                  (f"$P{i}E", "0,0"), (f"$P{i}G", "1")]
    text = ("|" + "|".join(part for pair in pairs for part in pair) + "|").encode("ascii")
    header = (f"FCS{version}    " + "".join(f"{n:8d}" for n in (58, 57+len(text), begin, end, 0, 0))).encode("ascii")
    assert len(header) == 58
    return header + text + b" " * (begin - len(header) - len(text)) + data


def config():
    return {"schema_version": "yeast-facs-analysis-config/v1", "sample_id": "synthetic-count",
            "evidence_kind": "synthetic", "channels": NAMES[:2],
            "compensation": {"state": "uncompensated", "reason": "Independent synthetic reference"}}


@pytest.mark.parametrize("declared", [0, 1, 2, 4, 3000000])
def test_mismatched_tot_rejected_before_workspace_mutation_and_native_analysis(tmp_path, declared):
    data = fcs(declared=declared)
    engine = AnalysisEngine()
    valid = engine.load(fcs(), "valid.fcs")
    with pytest.raises(ValueError, match=r"FCS DATA:.*\$TOT.*decoded"):
        engine.load(data, "mismatched.fcs")
    assert list(engine.samples) == [valid["id"]]
    path = tmp_path / "synthetic-count.fcs"
    path.write_bytes(data)
    # Inspection promises only HEADER/TEXT, not event validation.
    assert inspect_fcs(path)["event_count_declared"] == declared
    with pytest.raises(ValueError, match=r"FCS DATA:.*\$TOT.*decoded"):
        analyze_fcs(path, config())
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config()), encoding="utf-8")
    output = tmp_path / "must-not-exist.json"
    assert core_main(["analyze", str(path), "--config", str(cfg), "--output", str(output)]) == 2
    assert not output.exists()
    assert path.read_bytes() == data


def test_partial_event_has_clear_count_diagnostic_instead_of_reshape_error():
    with pytest.raises(ValueError, match=r"FCS DATA:.*decoded 8 values"):
        load_fcs_sample(fcs(values=[1] * 8))


@pytest.mark.parametrize("version", ["2.0", "3.0", "3.1"])
@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("kind,bits", [("F", None), ("D", None), ("I", None), ("I", [16, 32, 16])])
def test_matching_counts_retain_values_and_order_across_supported_encodings(tmp_path, version, endian, kind, bits):
    data = fcs(version=version, endian=endian, kind=kind, bits=bits)
    sample = load_fcs_sample(data, cache_original_events=True)
    assert sample.event_count == 3
    np.testing.assert_array_equal(sample.get_events(source="orig"), EVENTS)
    np.testing.assert_array_equal(sample.get_events(source="raw"), EVENTS)
    path = tmp_path / "synthetic-encoding.fcs"
    path.write_bytes(data)
    result = analyze_fcs(path, config())["samples"][0]
    assert result["selected_count"] == 3
    assert result["processing"]["selected_event_ranges"] == [[0, 3]]
    assert result["channels"]["FITC-A"]["median"] == 20
    assert result["source"]["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("archive", [False, True])
def test_multifile_intake_reports_bad_count_keeps_valid_source_and_export_order(monkeypatch, archive):
    store = SessionStore()
    monkeypatch.setattr(server, "sessions", store)
    good, bad = fcs(), fcs(declared=2)
    files = [("files", ("bad-count.fcs", bad)), ("files", ("valid.fcs", good))]
    if archive:
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("export/bad-count.fcs", bad)
            z.writestr("export/valid.fcs", good)
        files = [("files", ("synthetic-export.zip", packed.getvalue()))]
    with TestClient(server.app) as client:
        response = client.post("/api/upload", files=files)
        assert response.status_code == 200
        result = response.json()
        assert len(result["errors"]) == 1
        assert "bad-count.fcs" in result["errors"][0]["filename"]
        assert "FCS DATA:" in result["errors"][0]["error"]
        assert "decoded 9 values" in result["errors"][0]["error"]
        samples = client.get("/api/state").json()["samples"]
        assert len(samples) == 1 and samples[0]["events"] == 3
        assert samples[0]["sha256"] == hashlib.sha256(good).hexdigest()
        spec = {"sample_id": samples[0]["id"], "population": "root", "compensation": "raw",
                "x": {"channel": "FITC-A"}, "y": {"channel": "APC-A"}}
        exported = client.post("/api/export/events", json=spec)
        assert exported.status_code == 200, exported.text
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        assert [int(row["event_index_zero_based"]) for row in rows] == [0, 1, 2]
        assert [float(row["FITC-A"]) for row in rows] == [30, 10, 20]
        assert all(row["source_sha256"] == samples[0]["sha256"] for row in rows)
