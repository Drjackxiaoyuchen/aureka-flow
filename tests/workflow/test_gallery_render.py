"""Bounded optional gallery checks: one small render, all data invented.

Figure labels are inspected on the actual Matplotlib figure at PNG/SVG save
time; these tests do not claim OCR or browser layout review of raster pixels.
"""

from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from examples.workflows.gallery import build_gallery as gallery
from examples.workflows.gallery.synthetic_data import build_dataset

HAVE_GALLERY = all(importlib.util.find_spec(name) is not None for name in ("numpy", "matplotlib"))


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ("href", "src") and value:
                self.targets.append(value)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


@unittest.skipUnless(HAVE_GALLERY, "optional NumPy/Matplotlib gallery dependencies absent")
class GalleryRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="synthetic-gallery-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.output = cls.base / "gallery"
        cls.seed = 20261001
        cls.events_per_sample = 100
        cls.saved_labels = {}
        # Capture labels from the same figure that is written to each output.
        from matplotlib.figure import Figure
        original_savefig = Figure.savefig

        def save_and_record(figure, filename, *args, **kwargs):
            cls.saved_labels[Path(filename).name] = [item.get_text() for item in figure.texts]
            return original_savefig(figure, filename, *args, **kwargs)

        with patch.object(Figure, "savefig", new=save_and_record):
            cls.summary = gallery.build_gallery(cls.output, seed=cls.seed, events_per_sample=cls.events_per_sample)
        # A fresh same-seed generation checks numerical reproducibility without
        # paying for a second figure-render pass.
        cls.reference_data = build_dataset(seed=cls.seed, events_per_sample=cls.events_per_sample)

    @classmethod
    def load(cls, relative):
        return json.loads((cls.output / relative).read_text(encoding="utf-8"))

    def test_four_png_and_four_svg_outputs_are_nonempty_and_valid(self):
        expected = {name + suffix for name, _, _ in gallery.FIGURES for suffix in (".png", ".svg")}
        actual = {path.name for path in (self.output / "figures").iterdir()}
        self.assertEqual(8, len(expected))
        self.assertEqual(expected, actual)
        for name in expected:
            with self.subTest(name=name):
                content = (self.output / "figures" / name).read_bytes()
                self.assertGreater(len(content), 1000)
                if name.endswith(".png"):
                    self.assertEqual(b"\x89PNG\r\n\x1a\n", content[:8])
                    self.assertEqual(b"IHDR", content[12:16])
                    width, height = struct.unpack(">II", content[16:24])
                    self.assertGreater(width, 1000)
                    self.assertGreater(height, 600)
                else:
                    self.assertEqual("{http://www.w3.org/2000/svg}svg", ET.fromstring(content).tag)

    def test_all_figures_labeled_synthetic_for_both_formats(self):
        self.assertEqual(8, len(self.saved_labels))
        for filename, labels in self.saved_labels.items():
            with self.subTest(filename=filename):
                self.assertTrue(any("SYNTHETIC ILLUSTRATION" in label for label in labels))
                self.assertTrue(any("NOT EXPERIMENTAL DATA" in label for label in labels))
        for name, _, _ in gallery.FIGURES:
            root = ET.parse(self.output / "figures" / (name + ".svg")).getroot()
            rendered_text = " ".join(root.itertext())
            self.assertIn("SYNTHETIC ILLUSTRATION", rendered_text)
            self.assertIn("NOT EXPERIMENTAL DATA", rendered_text)

    def test_summary_counts_agree_with_event_masks_and_workflow(self):
        measurements = self.load("workflow/measurements.json")
        experiment = self.load("workflow/05-report/experiment.json")
        summary = self.load("summary.json")
        self.assertEqual(self.summary, summary)
        self.assertEqual("synthetic", summary["evidence_kind"])
        self.assertFalse(summary["biological_validation"])
        self.assertEqual(9, len(summary["samples"]))
        self.assertEqual(900, summary["counts"]["input"])
        self.assertEqual(900, sum(s["event_count"] for s in measurements["samples"]))
        expected_counts = {
            "input": sum(len(s["events"]) for s in self.reference_data["samples"]),
            "after_time_mask": sum(int(s["qc_mask"].sum()) for s in self.reference_data["samples"]),
            "after_expression_gate": sum(int(s["selected_mask"].sum()) for s in self.reference_data["samples"]),
        }
        self.assertEqual(expected_counts, summary["counts"])
        self.assertEqual(summary["counts"]["after_time_mask"], sum(s["processing"]["stage_counts"]["after_external_qc_mask"] for s in measurements["samples"]))
        self.assertEqual(summary["counts"]["after_expression_gate"], sum(s["selected_count"] for s in experiment["samples"]))
        self.assertEqual(experiment["comparison_status"], summary["comparison_status"])
        for actual, expected in zip(summary["samples"], experiment["samples"]):
            for field in ("sample_id", "condition", "event_count", "selected_count", "channels", "source"):
                self.assertEqual(expected[field], actual[field])

    def test_source_hashes_describe_reproducible_synthetic_arrays_not_files(self):
        by_id = {sample["sample_id"]: sample for sample in self.summary["samples"]}
        hashes = set()
        for sample in self.reference_data["samples"]:
            encoded = (json.dumps(sample["events"].tolist(), separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            expected = hashlib.sha256(encoded).hexdigest()
            source = by_id[sample["sample_id"]]["source"]
            self.assertEqual(expected, source["sha256"])
            self.assertEqual(Path(source["basename"]).name, source["basename"])
            self.assertTrue(source["basename"].endswith("-events.json"))
            hashes.add(expected)
        self.assertEqual(9, len(hashes))
        self.assertIn("not an FCS file", self.summary["simulation"]["source_hash_serialization"])
        self.assertEqual([], self.summary["simulation"]["real_data_sources"])
        self.assertEqual(0, self.summary["simulation"]["real_biological_replicates"])

    def test_summary_has_no_absolute_paths(self):
        for value in strings(self.summary):
            self.assertFalse(Path(value).is_absolute(), value)
            self.assertNotIn(str(self.base), value)
            self.assertNotIn("/Users/", value)
            self.assertNotIn("/Volumes/", value)
        self.assertEqual({"python", "numpy", "matplotlib"}, set(self.summary["software"]))

    def test_manifest_hashes_cover_every_output_except_itself(self):
        manifest = self.load("gallery-manifest.json")
        self.assertEqual("yeast-facs-gallery-manifest/v1", manifest["schema_version"])
        self.assertEqual(self.seed, manifest["seed"])
        self.assertEqual(self.summary["software"], manifest["software"])
        recorded = [entry["path"] for entry in manifest["files"]]
        expected = {path.relative_to(self.output).as_posix() for path in self.output.rglob("*") if path.is_file()} - {"gallery-manifest.json"}
        self.assertEqual(len(recorded), len(set(recorded)))
        self.assertEqual(expected, set(recorded))
        for entry in manifest["files"]:
            path = Path(entry["path"])
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            self.assertEqual(hashlib.sha256((self.output / path).read_bytes()).hexdigest(), entry["sha256"])
        self.assertIn("workflow/run-receipt.json", recorded)

    def test_same_seed_reproduces_data_bearing_summary_without_second_render(self):
        data = self.reference_data
        expected = {
            "schema_version": "yeast-facs-gallery-summary/v1", "evidence_kind": "synthetic",
            "simulation": data["metadata"],
            "display_transforms": {"FITC-A": "log10; synthetic expression values are positive", "APC-A": "asinh(value / 20); preserves negative values; ticks labeled in original arbitrary units"},
            "counts": {"input": sum(len(s["events"]) for s in data["samples"]),
                       "after_time_mask": sum(int(s["qc_mask"].sum()) for s in data["samples"]),
                       "after_expression_gate": sum(int(s["selected_mask"].sum()) for s in data["samples"])},
            "samples": [{"sample_id": s["sample_id"], "condition": s["condition"], "simulated_replicate": s["biological_replicate"],
                         "event_count": s["event_count"], "selected_count": s["selected_count"], "channels": s["channels"], "source": s["source"]}
                        for s in data["experiment"]["samples"]],
            "sort_bins": data["linked"]["bins"], "linked_counts": data["linked"]["linked_counts"],
            "comparison_status": data["experiment"]["comparison_status"], "biological_validation": False,
        }
        actual = deepcopy(self.summary)
        actual.pop("software")
        self.assertEqual(expected, actual)

    def test_all_generated_html_links_and_images_resolve_locally(self):
        html_files = list(self.output.rglob("*.html"))
        self.assertGreaterEqual(len(html_files), 4)
        for path in html_files:
            parser = Links()
            parser.feed(path.read_text(encoding="utf-8"))
            for target in parser.targets:
                with self.subTest(html=path.relative_to(self.output).as_posix(), target=target):
                    parsed = urlsplit(target)
                    self.assertFalse(parsed.scheme, "Gallery HTML must not require remote resources")
                    self.assertFalse(parsed.netloc)
                    if parsed.path:
                        resolved = (path.parent / unquote(parsed.path)).resolve()
                        self.assertTrue(resolved.is_relative_to(self.output.resolve()))
                        self.assertTrue(resolved.is_file(), str(resolved))

    def test_existing_output_refused_without_modifying_files_or_loading_deps(self):
        before = {path.relative_to(self.output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.output.rglob("*") if path.is_file()}
        with patch.object(gallery, "dependencies", side_effect=AssertionError("dependencies must not load")):
            with self.assertRaisesRegex(ValueError, "fresh"):
                gallery.build_gallery(self.output, events_per_sample=100)
        after = {path.relative_to(self.output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.output.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_dangling_output_symlink_refused(self):
        link = self.base / "dangling-output"
        target = self.base / "must-stay-absent"
        link.symlink_to(target, target_is_directory=True)
        with patch.object(gallery, "dependencies", side_effect=AssertionError("dependencies must not load")):
            with self.assertRaisesRegex(ValueError, "fresh"):
                gallery.build_gallery(link, events_per_sample=100)
        self.assertFalse(target.exists())
        self.assertTrue(link.is_symlink())

    def test_display_transforms_preserve_negative_binding_and_do_not_change_gate(self):
        import numpy as np
        self.assertEqual(20, gallery.COFACTOR)
        transformed = np.arcsinh(np.array([-100.0, 0.0, 100.0]) / gallery.COFACTOR)
        self.assertLess(transformed[0], 0)
        self.assertEqual(0, transformed[1])
        self.assertGreater(transformed[2], 0)
        for sample in self.reference_data["samples"]:
            self.assertTrue(np.all(sample["events"][:, 2] > 0))
            self.assertTrue(np.array_equal(sample["selected_mask"], sample["qc_mask"] & (sample["events"][:, 2] >= 400)))
        self.assertIn("preserves negative values", self.summary["display_transforms"]["APC-A"])

    def test_sort_summary_remains_independent_and_uses_read_denominators(self):
        self.assertTrue(self.summary["simulation"]["sort_count_model"]["independent_of_event_cloud"])
        self.assertEqual(4, len(self.summary["sort_bins"]))
        self.assertEqual(32, len(self.summary["linked_counts"]))
        by_seq = {}
        for row in self.summary["linked_counts"]:
            self.assertEqual(row["read_count"] / row["total_reads_in_sequencing_sample"], row["read_fraction_within_sequencing_sample"])
            by_seq.setdefault(row["sequencing_sample_id"], []).append(row)
        for rows in by_seq.values():
            self.assertEqual(8, len(rows))
            self.assertAlmostEqual(1.0, sum(row["read_fraction_within_sequencing_sample"] for row in rows))


if __name__ == "__main__":
    unittest.main()
