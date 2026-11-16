"""Offline documentation integrity checks; not scientific or visual validation."""
import json
from pathlib import Path
import re
import struct
import unittest
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = sorted((ROOT / "docs" / "workflows").rglob("*.md"))
LINK = re.compile(r"\[[^\]\n]*\]\(([^\s)]+)\)")


def links():
    for document in DOCUMENTS:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            parsed = urlsplit(target)
            if not parsed.scheme and not parsed.netloc:
                path = document.parent / unquote(parsed.path) if parsed.path else document
                yield document, path.resolve(), unquote(parsed.fragment)


def heading_ids(document):
    """GitHub-style slugs for the ordinary headings used by these documents."""
    result, counts, fenced = set(), {}, False
    for line in document.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if fenced or not re.match(r"^#{1,6} ", line):
            continue
        title = re.sub(r"^#{1,6} ", "", line).strip().lower()
        slug = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
        number = counts.get(slug, 0)
        counts[slug] = number + 1
        result.add(f"{slug}-{number}" if number else slug)
    return result


class DocumentationTests(unittest.TestCase):
    def test_relative_markdown_targets_exist_and_stay_in_repository(self):
        for document, target, _ in links():
            with self.subTest(document=document.name, target=str(target)):
                self.assertTrue(target.is_relative_to(ROOT))
                self.assertTrue(target.exists())

    def test_markdown_heading_links_resolve(self):
        for document, target, fragment in links():
            if fragment and target.suffix == ".md":
                with self.subTest(document=document.name, fragment=fragment):
                    self.assertIn(fragment, heading_ids(target))

    def test_workflow_svg_is_accessible_static_and_contains_six_stage_labels(self):
        root = ET.parse(ROOT / "docs/workflows/figures/workflow-overview.svg").getroot()
        ns = {"svg": "http://www.w3.org/2000/svg"}
        self.assertEqual("img", root.attrib["role"])
        self.assertTrue(root.find("svg:title", ns).text.strip())
        self.assertTrue(root.find("svg:desc", ns).text.strip())
        labels = {"".join(node.itertext()).strip() for node in root.findall(".//svg:text", ns)}
        self.assertTrue({"01", "02", "03", "04", "05", "06"}.issubset(labels))
        for node in root.iter():
            self.assertNotIn(node.tag.rsplit("}", 1)[-1], {"script", "foreignObject"})
            for name, value in node.attrib.items():
                if name.rsplit("}", 1)[-1] == "href":
                    self.assertTrue(value.startswith("#"), value)

    def test_workflow_png_has_high_resolution_portrait_dimensions(self):
        data = (ROOT / "docs/workflows/figures/workflow-overview.png").read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
        self.assertEqual(b"IHDR", data[12:16])
        width, height = struct.unpack(">II", data[16:24])
        self.assertGreaterEqual(width, 1600)
        self.assertGreater(height, width)
        self.assertLess(height, 6000)

    def test_worked_review_values_match_committed_synthetic_summary(self):
        data = json.loads((ROOT / "docs/workflows/gallery/summary.json").read_text())
        sample = next(s for s in data["samples"] if s["sample_id"] == "synthetic-shift-b-r1")
        self.assertEqual(3000, sample["event_count"])
        self.assertEqual(2283, sample["selected_count"])
        self.assertEqual(2283, sample["channels"]["APC-A"]["finite_count"])
        self.assertAlmostEqual(976.0061384395848, sample["channels"]["APC-A"]["median"])
        self.assertEqual({"input": 27000, "after_time_mask": 23994, "after_expression_gate": 20634}, data["counts"])
        row = next(r for r in data["linked_counts"] if r["sequencing_sample_id"] == "synthetic-seq-bin-1" and r["variant_id"] == "synthetic-variant-01")
        self.assertEqual(9311, row["read_count"])
        self.assertEqual(24000, row["total_reads_in_sequencing_sample"])
        self.assertEqual(8000, row["sorted_events"])
        self.assertAlmostEqual(9311 / 24000, row["read_fraction_within_sequencing_sample"])
        guide = (ROOT / "docs/workflows/workflow-review.md").read_text()
        for value in ("2,666", "2,283", "976.0061384395848", "9,311", "24,000", "8,000"):
            self.assertIn(value, guide)


if __name__ == "__main__":
    unittest.main()
