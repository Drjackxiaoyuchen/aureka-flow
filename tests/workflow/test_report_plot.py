"""Original SVG chart checks using synthetic summaries only."""

import math
from pathlib import Path
import re
import sys
import unittest
from xml.etree import ElementTree as ET


from aureka_flow.workflows.workbench.analysis import analyze
from aureka_flow.workflows.workbench.report import median_dot_plot, render_report

SVG = "{http://www.w3.org/2000/svg}"


def sample(value, index=1, *, detector="Synthetic-A", supplied=True):
    return {"sample_id": f"synthetic-sample-{index}", "event_count": 10, "selected_count": 10,
            "gate_status": "ungated", "processing": {"fixture": "SYNTHETIC"}, "qc_flags": [],
            "channels": {detector: {"median": value, "finite_count": 0 if value is None else 9}} if supplied else {}}


def extract_svg(markup):
    match = re.search(r"<svg\b.*?</svg>", markup, flags=re.S)
    if match is None:
        raise AssertionError("No SVG emitted")
    return ET.fromstring(match.group())


def circles(svg):
    return svg.findall(f"{SVG}circle")


def zero(svg):
    return next(e for e in svg.findall(f"{SVG}line") if e.get("class") == "zero-reference")


class ReportPlotTests(unittest.TestCase):
    def assert_finite_coordinates(self, svg):
        for element in svg.iter():
            for name in ("x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "width", "height"):
                if name in element.attrib:
                    self.assertTrue(math.isfinite(float(element.attrib[name])), (name, element.attrib[name]))
        for dot in circles(svg):
            self.assertGreaterEqual(float(dot.get("cx")), 260)
            self.assertLessEqual(float(dot.get("cx")), 775)

    def test_all_missing_and_absent_values_are_not_zero_dots(self):
        markup = median_dot_plot([sample(None), sample(None, 2, supplied=False)], "Synthetic-A")
        svg = extract_svg(markup)
        self.assertEqual([], circles(svg))
        self.assertIn("No finite medians", markup)
        self.assertIn("Unavailable", markup)
        self.assertIn("Not supplied", markup)
        self.assertIn("0 / 10", markup)
        self.assertIn("not supplied / 10", markup)
        self.assert_finite_coordinates(svg)

    def test_empty_samples_render_without_coordinates_nan(self):
        markup = median_dot_plot([], "Synthetic-A")
        svg = extract_svg(markup)
        self.assertEqual([], circles(svg))
        self.assertIn("0 individual sample records", markup)
        self.assert_finite_coordinates(svg)

    def test_singleton_has_single_median_and_zero_reference(self):
        markup = median_dot_plot([sample(42)], "Synthetic-A")
        svg = extract_svg(markup)
        self.assertEqual(1, len(circles(svg)))
        self.assertGreater(float(circles(svg)[0].get("cx")), float(zero(svg).get("x1")))
        self.assertIn("9 / 10", markup)
        self.assertIn("not a biological cutoff", markup)
        self.assert_finite_coordinates(svg)

    def test_negative_zero_positive_order_preserved(self):
        svg = extract_svg(median_dot_plot([sample(-5), sample(0, 2), sample(5, 3)], "Synthetic-A"))
        coordinates = [float(dot.get("cx")) for dot in circles(svg)]
        zx = float(zero(svg).get("x1"))
        self.assertLess(coordinates[0], zx)
        self.assertEqual(coordinates[1], zx)
        self.assertGreater(coordinates[2], zx)
        self.assert_finite_coordinates(svg)

    def test_all_negative_zero_is_right_reference(self):
        svg = extract_svg(median_dot_plot([sample(-8), sample(-3, 2)], "Synthetic-A"))
        self.assertEqual(775, float(zero(svg).get("x1")))
        self.assertLess(float(circles(svg)[0].get("cx")), float(circles(svg)[1].get("cx")))

    def test_all_zero_no_invented_range(self):
        markup = median_dot_plot([sample(0), sample(0, 2)], "Synthetic-A")
        svg = extract_svg(markup)
        zx = float(zero(svg).get("x1"))
        self.assertTrue(all(float(dot.get("cx")) == zx for dot in circles(svg)))
        self.assertIn("All displayed finite medians are zero", markup)
        self.assert_finite_coordinates(svg)

    def test_opposite_huge_finite_values_do_not_overflow(self):
        svg = extract_svg(median_dot_plot([sample(-1.7e308), sample(0, 2), sample(1.7e308, 3)], "Synthetic-A"))
        self.assertEqual([260.0, 517.5, 775.0], [float(dot.get("cx")) for dot in circles(svg)])
        self.assert_finite_coordinates(svg)

    def test_same_sign_huge_values_keep_order(self):
        svg = extract_svg(median_dot_plot([sample(1e308), sample(1.7e308, 2)], "Synthetic-A"))
        x = [float(dot.get("cx")) for dot in circles(svg)]
        self.assertLess(x[0], x[1])
        self.assert_finite_coordinates(svg)

    def test_subnormal_values_not_collapsed_to_zero(self):
        svg = extract_svg(median_dot_plot([sample(-5e-324), sample(0, 2), sample(5e-324, 3)], "Synthetic-A"))
        self.assertEqual([260.0, 517.5, 775.0], [float(dot.get("cx")) for dot in circles(svg)])
        self.assert_finite_coordinates(svg)

    def test_numeric_junk_rejected_even_when_called_directly(self):
        for value in (True, "1", float("nan"), float("inf"), 10 ** 400):
            with self.subTest(value=str(value)[:25]), self.assertRaisesRegex(ValueError, "finite numeric"):
                median_dot_plot([sample(value)], "Synthetic-A")

    def test_injected_labels_and_detector_title_are_escaped(self):
        payload = '<script>alert("SYNTHETIC")</script><img src=x onerror="go()">'
        row = sample(2, detector=payload)
        row["sample_id"] = payload
        markup = median_dot_plot([row], payload)
        svg = extract_svg(markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<img ", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertEqual("img", svg.get("role"))
        self.assertIn(payload, svg.get("aria-label"))
        self.assertIn(payload, "".join(svg.itertext()))
        self.assertEqual({"svg", "title", "desc", "line", "text", "circle"}, {e.tag.removeprefix(SVG) for e in svg.iter()})

    def test_long_sample_labels_keep_full_text_in_title(self):
        row = sample(5)
        row["sample_id"] = "synthetic-" + "long-label-" * 15
        svg = extract_svg(median_dot_plot([row], "Synthetic-A"))
        self.assertIn(row["sample_id"], [title.text for title in svg.iter(f"{SVG}title")])
        self.assertIn("…", "".join(svg.itertext()))

    def test_visual_cap_leaves_complete_table_and_explicit_truncation(self):
        rows = [sample(index, index) for index in range(1, 53)]
        measurements = {"schema_version": "yeast-facs-measurements/v1", "evidence_kind": "synthetic", "samples": rows}
        manifest = {"schema_version": "yeast-facs-samples/v1", "samples": [
            {"sample_id": row["sample_id"], "condition": "synthetic", "biological_replicate": None, "batch_id": None, "plate": None, "well": None, "control_role": "sample"}
            for row in rows]}
        html = render_report(analyze(measurements, manifest))
        svg = extract_svg(html)
        self.assertEqual(50, len(circles(svg)))
        self.assertIn("Plot truncated: first 50 of 52", html)
        self.assertNotIn("synthetic-sample-52", "".join(svg.itertext()))
        self.assertIn("<td>synthetic-sample-52</td>", html)
        self.assertIn("Axis uses displayed rows only", html)
        self.assert_finite_coordinates(svg)

    def test_one_svg_per_detector_with_individual_not_pooled_points(self):
        rows = [sample(2), sample(6, 2)]
        for row in rows:
            row["channels"]["Synthetic-B"] = {"median": None, "finite_count": 0}
        measurements = {"schema_version": "yeast-facs-measurements/v1", "evidence_kind": "synthetic", "samples": rows}
        manifest = {"schema_version": "yeast-facs-samples/v1", "samples": [
            {"sample_id": row["sample_id"], "condition": "synthetic", "biological_replicate": None, "batch_id": None, "plate": None, "well": None, "control_role": "sample"}
            for row in rows]}
        html = render_report(analyze(measurements, manifest))
        matches = re.findall(r"<svg\b.*?</svg>", html, flags=re.S)
        self.assertEqual(2, len(matches))
        self.assertEqual([2, 0], [len(circles(ET.fromstring(svg))) for svg in matches])
        self.assertIn("no pooled estimates", html)
        self.assertIn("do not establish comparable detector units", html)


if __name__ == "__main__":
    unittest.main()
