"""Synthetic ZIP/FCS fixtures verify identity, limits and partial-failure semantics."""
import hashlib
import io
import json
import stat
import struct
import zipfile
import zlib

import flowio
import pytest
from fastapi.testclient import TestClient

from aureka_flow import archive_intake, server
from aureka_flow.sessions import SessionStore


def fcs(offset=0):
    handle = io.BytesIO()
    flowio.create_fcs(handle, [3 + offset, 6, 1 + offset, 2, 2 + offset, 4], ["FITC-A", "APC-A"])
    return handle.getvalue()


def packed(entries, compression=zipfile.ZIP_DEFLATED):
    handle = io.BytesIO()
    with zipfile.ZipFile(handle, "w", compression=compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return handle.getvalue()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "sessions", SessionStore())
    with TestClient(server.app) as client:
        yield client


def upload(client, data, name="export.zip"):
    result = client.post("/api/upload", files=[("files", (name, data))])
    assert result.status_code == 200
    return result.json()


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_nested_and_unicode_paths_same_basename_keep_distinct_hashes_and_event_order(client, compression):
    first, second = fcs(), fcs(10)
    data = packed([("α/sample.FCS", first), ("β/sample.fcs", second), ("sort-report.pdf", b"ignored"),
                   ("__MACOSX/._sample.fcs", b"resource fork")], compression)
    result = upload(client, data)
    assert not result["errors"] and len(result["samples"]) == 2
    assert len(result["skipped"]) == 2
    assert {s["filename"] for s in result["samples"]} == {"sample.FCS", "sample.fcs"}
    assert len({s["id"] for s in result["samples"]}) == 2
    project = client.get("/api/project").json()
    assert len(project["samples"]) == 2
    for sample, original, path in zip(project["samples"], [first, second], ["α/sample.FCS", "β/sample.fcs"]):
        assert sample["sha256"] == hashlib.sha256(original).hexdigest()
        assert sample["source_containers"] == [{"filename": "export.zip", "sha256": hashlib.sha256(data).hexdigest(),
            "member_path": path, "member_crc32": f"{zlib.crc32(original):08x}"}]
        spec = {"sample_id": sample["id"], "x": {"channel": "FITC-A"}, "y": {"channel": "APC-A"}}
        response = client.post("/api/export/events", json=spec)
        import pandas as pd
        frame = pd.read_csv(io.BytesIO(response.content))
        assert frame["event_index_zero_based"].tolist() == [0, 1, 2]
        assert frame["FITC-A"].tolist() == ([3, 1, 2] if original == first else [13, 11, 12])


def test_duplicate_memberships_keep_one_sample_and_charge_global_budget_once(monkeypatch):
    source = fcs()
    monkeypatch.setattr(server, "sessions", SessionStore(budget=len(source)))
    data = packed([("tube-a.fcs", source), ("tube-b.fcs", source)])
    with TestClient(server.app) as client:
        result = upload(client, data)
        assert not result["errors"]
        assert len({s["id"] for s in result["samples"]}) == 1
        assert len(client.get("/api/state").json()["samples"]) == 1
        assert len(client.get("/api/project").json()["samples"][0]["source_containers"]) == 2
        assert not upload(client, data)["errors"]
        assert len(client.get("/api/project").json()["samples"][0]["source_containers"]) == 2
        workspace = next(iter(server.sessions.workspaces.values()))
        assert workspace.input_bytes == len(source) and workspace.reserved_bytes == 0


def test_corrupt_fcs_member_does_not_hide_valid_sample_or_leak_reservation(client):
    result = upload(client, packed([("broken.fcs", b"incomplete FCS"), ("good.fcs", fcs())]))
    assert len(result["samples"]) == 1 and len(result["errors"]) == 1
    assert result["errors"][0]["filename"] == "export.zip / broken.fcs"
    assert len(client.get("/api/state").json()["samples"]) == 1
    assert all(w.reserved_bytes == 0 for w in server.sessions.workspaces.values())


@pytest.mark.parametrize("name", ["../escape.fcs", "/absolute.fcs", "C:\\escape.fcs", "nested/../escape.fcs"])
def test_unsafe_member_paths_reject_archive_before_loading_any_members(client, name):
    result = upload(client, packed([("good.fcs", fcs()), (name, fcs(1))]))
    assert result["samples"] == [] and "unsafe" in result["errors"][0]["error"]
    assert client.get("/api/state").json()["samples"] == []


def test_duplicate_normalized_paths_reject_before_mutation(client):
    result = upload(client, packed([("folder/a.fcs", fcs()), ("folder\\a.fcs", fcs(1))]))
    assert result["samples"] == [] and "duplicate" in result["errors"][0]["error"]


def test_symlink_members_are_not_followed(client):
    link = zipfile.ZipInfo("link.fcs")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    result = upload(client, packed([("good.fcs", fcs()), (link, b"/private/file")]))
    assert result["samples"] == [] and "regular files" in result["errors"][0]["error"]


@pytest.mark.parametrize("entries, error", [
    ([("report.pdf", b"report"), ("nested.zip", b"archive")], "No FCS"),
    ([(f"sample-{n}.fcs", b"FCS") for n in range(25)], "24 FCS"),
    ([(f"entry-{n}.txt", b"") for n in range(257)], "directory limit"),
])
def test_non_sample_and_oversized_archives_are_explicit(client, entries, error):
    result = upload(client, packed(entries))
    assert result["samples"] == [] and error in result["errors"][0]["error"]


def test_expanded_file_and_request_budgets_are_checked_before_parse(client, monkeypatch):
    monkeypatch.setattr(server.config, "MAX_FILE_BYTES", 1024)
    result = upload(client, packed([("large.fcs", b"0" * 5000)]))
    assert result["samples"] == [] and "per-file" in result["errors"][0]["error"]
    monkeypatch.setattr(server.config, "MAX_FILE_BYTES", 100 * 1024**2)
    monkeypatch.setattr(server.config, "MAX_TOTAL_BYTES", len(fcs()) + 1)
    result = upload(client, packed([("a.fcs", fcs()), ("b.fcs", fcs(1))]))
    assert result["samples"] == [] and "request budget" in result["errors"][0]["error"]


def test_expanded_budget_applies_across_archives_and_bare_files(client, monkeypatch):
    source = fcs()
    monkeypatch.setattr(server.config, "MAX_TOTAL_BYTES", len(source) + 1)
    response = client.post("/api/upload", files=[("files", ("first.fcs", source)),
        ("files", ("second.zip", packed([("b.fcs", fcs(1))])))])
    result = response.json()
    assert len(result["samples"]) == 1 and "request budget" in result["errors"][0]["error"]


@pytest.mark.parametrize("offset, fmt, value, error", [
    (10, "H", 257, "directory limit"), (12, "I", 3 * 1024**2, "directory limit"),
    (10, "H", 65535, "ZIP64"), (4, "H", 1, "Split ZIP"),
])
def test_directory_precheck_runs_before_metadata_allocation(monkeypatch, offset, fmt, value, error):
    data = bytearray(packed([("a.fcs", fcs())]))
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<" + fmt, data, end + offset, value)
    if offset == 10:
        struct.pack_into("<H", data, end + 8, value)
    monkeypatch.setattr(archive_intake.zipfile, "ZipFile", lambda *_: pytest.fail("Directory allocation before budget check"))
    with pytest.raises(ValueError, match=error):
        with archive_intake.fcs_archive(bytes(data), file_limit=10000, expanded_limit=10000):
            pass


def test_incomplete_crc_failure_encryption_and_unsupported_compression(client):
    source = fcs()
    truncated = upload(client, packed([("a.fcs", source)])[:-10])
    assert not truncated["samples"] and truncated["errors"]
    data = bytearray(packed([("a.fcs", source)], zipfile.ZIP_STORED))
    filename_length, extra_length = struct.unpack_from("<HH", data, 26)
    data[30 + filename_length + extra_length] ^= 1
    result = upload(client, bytes(data))
    assert not result["samples"] and "CRC" in result["errors"][0]["error"]
    data = bytearray(packed([("a.fcs", source)]))
    central = data.find(b"PK\x01\x02")
    struct.pack_into("<H", data, central + 8, 1)
    result = upload(client, bytes(data))
    assert not result["samples"] and "Encrypted" in result["errors"][0]["error"]
    result = upload(client, packed([("a.fcs", source)], zipfile.ZIP_BZIP2))
    assert not result["samples"] and "Deflate" in result["errors"][0]["error"]


def test_archive_provenance_survives_analysis_zip(client):
    result = upload(client, packed([("experiment/tube.fcs", fcs())]))
    info = result["samples"][0]
    response = client.post("/api/export/bundle?include_events=false", json={"sample_ids": [info["id"]],
        "x": {"channel": "FITC-A"}, "y": {"channel": "APC-A"}})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert json.loads(archive.read("manifest.json"))["sources"][0]["source_containers"] == info["source_containers"]
        assert json.loads(archive.read("project.json"))["samples"][0]["sha256"] == info["sha256"]
