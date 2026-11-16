"""Offline checks of published-summary replots, not new affinity fits."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from examples.workflows.papers import build_paper_gallery as gallery

HAVE_PLOTTING = importlib.util.find_spec("matplotlib") is not None
INPUT = ROOT / "examples/workflows/papers/data/adams-2016-table1.json"


@unittest.skipUnless(HAVE_PLOTTING, "optional Matplotlib gallery dependency absent")
class PaperRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="paper-render-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name).resolve()
        cls.output = cls.base / "gallery"
        cls.summary = gallery.build(INPUT, cls.output)

    def test_four_nonempty_png_svg_assets(self):
        for name in gallery.FIGURES:
            png = (self.output / (name + ".png")).read_bytes()
            self.assertEqual(b"\x89PNG\r\n\x1a\n", png[:8])
            width, height = struct.unpack(">II", png[16:24])
            self.assertGreaterEqual(width, 2000)
            self.assertGreaterEqual(height, 1300)
            svg = ET.parse(self.output / (name + ".svg")).getroot()
            self.assertEqual("{http://www.w3.org/2000/svg}svg", svg.tag)

    def test_figure_text_preserves_attribution_and_scope(self):
        for name in gallery.FIGURES:
            text = " ".join(ET.parse(self.output / (name + ".svg")).getroot().itertext())
            for expected in ("PUBLISHED DATA", "Adams et al.", "CC BY 4.0", "not new affinity fits"):
                self.assertIn(expected, text)

    def test_summary_pairs_bounds_and_no_new_fits(self):
        self.assertEqual("published_summary", self.summary["evidence_kind"])
        self.assertEqual(19, self.summary["clones"])
        self.assertEqual(14, self.summary["quantified_pairs"])
        self.assertEqual(["OPT", "C45", "C3", "C18", "Δ"], self.summary["limit_qualified_clones"])
        for key in ("new_affinity_fits", "raw_fcs_reprocessed", "workflow_biological_validation"):
            self.assertIs(False, self.summary[key])

    def test_input_and_derived_hashes(self):
        self.assertEqual(hashlib.sha256(INPUT.read_bytes()).hexdigest(), self.summary["source_table_sha256"])
        self.assertEqual(4, len(self.summary["derived_files"]))
        for name, record in self.summary["derived_files"].items():
            raw = (self.output / name).read_bytes()
            self.assertEqual(len(raw), record["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])

    def test_summary_matches_disk_and_has_no_machine_paths(self):
        self.assertEqual(self.summary, json.loads((self.output / "adams-summary.json").read_text()))
        text = json.dumps(self.summary)
        for prefix in ("/Users/", "/Volumes/", "/private/", "/tmp/"):
            self.assertNotIn(prefix, text)

    def test_existing_output_is_preserved(self):
        before = (self.output / "adams-summary.json").read_bytes()
        with self.assertRaises(ValueError):
            gallery.build(INPUT, self.output)
        self.assertEqual(before, (self.output / "adams-summary.json").read_bytes())

    def test_symlink_output_parent_is_rejected(self):
        link = self.base / "link"
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises(ValueError):
            gallery.build(INPUT, link / "nested")
        self.assertFalse((self.output / "nested").exists())

    def test_invalid_input_does_not_create_output(self):
        invalid = self.base / "invalid.json"
        data = json.loads(INPUT.read_text())
        data["rows"][3]["flow"]["sem_log10"] = None
        invalid.write_text(json.dumps(data))
        destination = self.base / "rejected"
        with self.assertRaises(ValueError):
            gallery.build(invalid, destination)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
