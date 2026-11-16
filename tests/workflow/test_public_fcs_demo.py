"""Archive/provenance safeguards using tiny invented bytes, never public FCS."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile


PATH = Path(__file__).resolve().parents[2] / "examples" / "workflows" / "papers" / "build_fcs_si_demo.py"
SPEC = importlib.util.spec_from_file_location("public_fcs_demo_under_test", PATH)
DEMO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEMO)


class ArchiveContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.archive = self.root / "fixture.zip"
        self.payloads = {"Fig 2A.fcs": b"invented blank fixture", "Fig 2BCD.fcs": b"invented cell fixture"}
        self.source = {}
        self.files = {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                      for name, raw in self.payloads.items()}
        self.make_zip()
        self.source_patch = patch.object(DEMO, "SOURCE", self.source)
        self.files_patch = patch.object(DEMO, "FILES", self.files)
        self.source_patch.start()
        self.files_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.addCleanup(self.files_patch.stop)

    def make_zip(self, *, omit=None, duplicate=None, symlink=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w") as handle:
                for name, raw in self.payloads.items():
                    if name == omit:
                        continue
                    if name == symlink:
                        info = zipfile.ZipInfo(name)
                        info.create_system = 3
                        info.external_attr = (0o120777 << 16)
                        handle.writestr(info, raw)
                    else:
                        handle.writestr(name, raw)
                    if name == duplicate:
                        handle.writestr(name, raw)
                # Unselected content is never extracted, even with unsafe names.
                handle.writestr("../../unselected.py", b"never executed or extracted")
        raw = self.archive.read_bytes()
        self.source.update(archive_bytes=len(raw), archive_md5=hashlib.md5(raw).hexdigest(),
                           archive_sha256=hashlib.sha256(raw).hexdigest())

    def test_exact_selected_bytes_only(self):
        before = set(self.root.iterdir())
        self.assertEqual(DEMO.verified_members(self.archive), self.payloads)
        self.assertEqual(set(self.root.iterdir()), before)

    def test_archive_size_mismatch(self):
        self.source["archive_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "size"):
            DEMO.verified_members(self.archive)

    def test_archive_sha256_mismatch(self):
        self.source["archive_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            DEMO.verified_members(self.archive)

    def test_publisher_md5_mismatch(self):
        self.source["archive_md5"] = "0" * 32
        with self.assertRaisesRegex(ValueError, "MD5"):
            DEMO.verified_members(self.archive)

    def test_missing_member(self):
        self.make_zip(omit="Fig 2A.fcs")
        with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
            DEMO.verified_members(self.archive)

    def test_duplicate_member(self):
        self.make_zip(duplicate="Fig 2BCD.fcs")
        with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
            DEMO.verified_members(self.archive)

    def test_selected_member_symlink(self):
        self.make_zip(symlink="Fig 2A.fcs")
        with self.assertRaisesRegex(ValueError, "symlink"):
            DEMO.verified_members(self.archive)

    def test_selected_member_size_mismatch(self):
        self.files["Fig 2A.fcs"]["bytes"] += 1
        with self.assertRaisesRegex(ValueError, "member size"):
            DEMO.verified_members(self.archive)

    def test_selected_member_hash_mismatch(self):
        self.files["Fig 2A.fcs"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "FCS SHA-256"):
            DEMO.verified_members(self.archive)

    def test_existing_output_is_preserved(self):
        output = self.root / "output"
        output.mkdir()
        sentinel = output / "retain.txt"
        sentinel.write_text("retain")
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            DEMO.build(self.archive, output)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "retain")

    def test_output_parent_symlink_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        link = self.root / "link"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink parents"):
            DEMO.build(self.archive, link / "new")
        self.assertFalse((actual / "new").exists())

    def test_dangling_output_symlink_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            DEMO.build(self.archive, link)

    def test_dotdot_output_rejected(self):
        with self.assertRaisesRegex(ValueError, "components"):
            DEMO.build(self.archive, self.root / "unused" / ".." / "output")

    def test_invalid_input_creates_no_output(self):
        self.source["archive_md5"] = "0" * 32
        output = self.root / "output"
        with self.assertRaisesRegex(ValueError, "MD5"):
            DEMO.build(self.archive, output)
        self.assertFalse(output.exists())


class PublicProvenanceTests(unittest.TestCase):
    def test_source_data_license_is_not_software_license(self):
        self.assertEqual(DEMO.SOURCE["license"], "CC-BY-4.0")
        self.assertEqual(DEMO.SOURCE["dataset_doi"], "10.1371/journal.pone.0250753.s001")
        self.assertIn("figshare.com", DEMO.SOURCE["dataset_metadata_url"])

    def test_public_mapping_is_bacterial_not_yeast(self):
        self.assertIn("E. coli", DEMO.FILES["Fig 2BCD.fcs"]["role"])
        self.assertIn("buffer blank", DEMO.FILES["Fig 2A.fcs"]["role"])
        self.assertEqual(DEMO.FILES["Fig 2A.fcs"]["events"], 13899)
        self.assertEqual(DEMO.FILES["Fig 2BCD.fcs"]["events"], 65689)

    def test_source_metadata_contains_no_local_paths(self):
        encoded = json.dumps({"source": DEMO.SOURCE, "files": DEMO.FILES})
        for private_marker in ("/Users/", "/Volumes/", "gmail.com", "Aureka"):
            self.assertNotIn(private_marker, encoded)
        self.assertEqual(len(DEMO.SOURCE["archive_sha256"]), 64)
        for info in DEMO.FILES.values():
            self.assertEqual(len(info["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
