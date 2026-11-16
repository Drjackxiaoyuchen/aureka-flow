"""Artificial fixtures only: contract and behavior checks, not assay validation."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aureka_flow.workflows.workbench import analyze, synthetic_manifest, ValidationError
from aureka_flow.workflows.workbench.cli import write_output
from aureka_flow.workflows.workbench.report import render_report
from aureka_flow.workflows.workbench.validation import read_json


def fixture():
    sample = {
        "sample_id": "synthetic-01", "event_count": 100, "selected_count": 80,
        "gate_status": "exploratory", "processing": {"fixture": "ARTIFICIAL", "transform": "none"},
        "channels": {"FITC-A": {"median": 250.0, "finite_count": 79}, "APC-A": {"median": -5.0, "finite_count": 80}},
        "qc_flags": [], "source": {"basename": "synthetic.csv", "sha256": "a" * 64},
        "extra_core_metadata": {"explicit": True},
    }
    measurements = {"schema_version": "yeast-facs-measurements/v1", "evidence_kind": "synthetic", "producer": "synthetic fixture", "samples": [sample]}
    metadata = {"sample_id": "synthetic-01", "condition": "artificial-A", "biological_replicate": "artificial-bio-1", "batch_id": "artificial-batch", "plate": "artificial-plate", "well": "A1", "control_role": "sample"}
    manifest = {"schema_version": "yeast-facs-samples/v1", "evidence_kind": "synthetic", "samples": [metadata]}
    return measurements, manifest


def duplicate_with_new_id(measurements, manifest, sample_id="synthetic-02", bio="artificial-bio-2"):
    measured, declared = deepcopy(measurements["samples"][0]), deepcopy(manifest["samples"][0])
    measured["sample_id"] = declared["sample_id"] = sample_id
    declared["biological_replicate"] = bio
    declared["well"] = "A2"
    measurements["samples"].append(measured)
    manifest["samples"].append(declared)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.measurements, self.manifest = fixture()

    def result(self):
        return analyze(self.measurements, self.manifest)

    def codes(self):
        return {warning["code"] for warning in self.result()["warnings"]}

    def test_valid_join_preserves_fields_and_inputs(self):
        before = deepcopy((self.measurements, self.manifest))
        result = self.result()
        self.assertEqual("yeast-facs-experiment/v1", result["schema_version"])
        for key, value in self.measurements["samples"][0].items():
            self.assertEqual(value, result["samples"][0][key])
        self.assertEqual("synthetic fixture", result["measurement_metadata"]["producer"])
        self.assertEqual(before, (self.measurements, self.manifest))
        result["samples"][0]["processing"]["fixture"] = "edited output"
        self.assertEqual(before, (self.measurements, self.manifest))

    def test_denominators_explicit(self):
        result = self.result()
        self.assertEqual(100, result["summary"]["acquired_event_count_sum"])
        self.assertEqual(80, result["summary"]["selected_event_count_sum"])
        self.assertIn("finite_denominator_differs", self.codes())
        html = render_report(result)
        self.assertIn("79 / 80", html)
        self.assertIn("80 / 100", html)
        self.assertIn("-5", html)

    def test_schema_versions(self):
        for document in (self.measurements, self.manifest):
            original = document["schema_version"]
            for value in (None, True, 1, "wrong/v1"):
                with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "schema_version"):
                    document["schema_version"] = value
                    self.result()
            document["schema_version"] = original

    def test_missing_required_field(self):
        for key in ("event_count", "selected_count", "processing", "channels", "qc_flags", "gate_status"):
            with self.subTest(key=key):
                sample = self.measurements["samples"][0]
                value = sample.pop(key)
                with self.assertRaisesRegex(ValidationError, key):
                    self.result()
                sample[key] = value

    def test_empty_sample_list(self):
        self.measurements["samples"] = []
        with self.assertRaisesRegex(ValidationError, "nonempty array"):
            self.result()

    def test_nonobject_root(self):
        with self.assertRaisesRegex(ValidationError, "object"):
            analyze([], self.manifest)

    def test_counts_reject_bool_and_numeric_junk(self):
        for key in ("event_count", "selected_count"):
            for value in (True, False, 3.0, "3", None, -1, [], {}):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValidationError, key):
                    measurements = deepcopy(self.measurements)
                    measurements["samples"][0][key] = value
                    analyze(measurements, self.manifest)

    def test_median_rejects_bool_string_nan_infinity_hugeint(self):
        for value in (True, "1", None, [], {}, float("nan"), float("inf"), -float("inf"), 10 ** 400):
            with self.subTest(value=str(value)[:25]), self.assertRaisesRegex(ValidationError, "median"):
                self.measurements["samples"][0]["channels"]["FITC-A"]["median"] = value
                self.result()

    def test_nested_metadata_nonfinite(self):
        self.measurements["samples"][0]["processing"]["bad"] = float("nan")
        with self.assertRaisesRegex(ValidationError, "processing.bad"):
            self.result()

    def test_count_ordering(self):
        self.measurements["samples"][0]["selected_count"] = 101
        with self.assertRaisesRegex(ValidationError, "selected_count"):
            self.result()

    def test_finite_count_ordering(self):
        self.measurements["samples"][0]["channels"]["FITC-A"]["finite_count"] = 81
        with self.assertRaisesRegex(ValidationError, "finite_count"):
            self.result()

    def test_finite_count_boolean(self):
        self.measurements["samples"][0]["channels"]["FITC-A"]["finite_count"] = True
        with self.assertRaisesRegex(ValidationError, "finite_count"):
            self.result()

    def test_zero_events_and_null_medians(self):
        sample = self.measurements["samples"][0]
        sample.update(event_count=0, selected_count=0)
        for channel in sample["channels"].values():
            channel.update(median=None, finite_count=0)
        self.assertIn("zero_selected_events", self.codes())
        self.assertIn("Unavailable", render_report(self.result()))

    def test_zero_count_nonnull_median_rejected(self):
        self.measurements["samples"][0]["channels"]["FITC-A"]["finite_count"] = 0
        with self.assertRaisesRegex(ValidationError, "median"):
            self.result()

    def test_ungated_must_retain_events(self):
        self.measurements["samples"][0]["gate_status"] = "ungated"
        with self.assertRaisesRegex(ValidationError, "ungated"):
            self.result()

    def test_duplicate_measurement_ids(self):
        self.measurements["samples"].append(deepcopy(self.measurements["samples"][0]))
        with self.assertRaisesRegex(ValidationError, "duplicate ID"):
            self.result()

    def test_duplicate_manifest_ids(self):
        self.manifest["samples"].append(deepcopy(self.manifest["samples"][0]))
        with self.assertRaisesRegex(ValidationError, "duplicate ID"):
            self.result()

    def test_unmatched_join(self):
        self.manifest["samples"][0]["sample_id"] = "different"
        with self.assertRaisesRegex(ValidationError, "missing manifest IDs.*unmatched manifest IDs"):
            self.result()

    def test_missing_manifest_join(self):
        duplicate_with_new_id(self.measurements, self.manifest)
        self.manifest["samples"].pop()
        with self.assertRaisesRegex(ValidationError, "missing manifest IDs"):
            self.result()

    def test_missing_biological_identity_warns_not_inferred(self):
        self.manifest["samples"][0]["biological_replicate"] = None
        result = self.result()
        self.assertEqual(0, result["condition_summaries"][0]["declared_biological_replicate_count"])
        self.assertEqual("metadata_limited", result["comparison_status"])
        self.assertIn("missing_biological_replicate", self.codes())

    def test_missing_batch_warns(self):
        self.manifest["samples"][0]["batch_id"] = None
        self.assertIn("missing_batch", self.codes())
        self.assertEqual("metadata_limited", self.result()["comparison_status"])

    def test_repeated_acquisitions_not_independent_replicates(self):
        duplicate_with_new_id(self.measurements, self.manifest, bio="artificial-bio-1")
        self.assertIn("repeated_biological_identity", self.codes())
        self.assertEqual(1, self.result()["condition_summaries"][0]["declared_biological_replicate_count"])

    def test_sufficient_declared_replicates_still_exploratory(self):
        duplicate_with_new_id(self.measurements, self.manifest)
        self.assertEqual("exploratory_only", self.result()["comparison_status"])

    def test_cross_batch_confounded_and_not_calibrated_by_reference(self):
        duplicate_with_new_id(self.measurements, self.manifest)
        self.manifest["samples"][1].update(batch_id="artificial-batch-2", condition="artificial-B", control_role="reference")
        result = self.result()
        self.assertEqual("cross_batch_blocked", result["comparison_status"])
        self.assertIn("condition_batch_confounding", self.codes())
        self.assertEqual(250, result["samples"][1]["channels"]["FITC-A"]["median"])

    def test_processing_and_channel_differences_visible(self):
        duplicate_with_new_id(self.measurements, self.manifest)
        self.measurements["samples"][1]["processing"]["transform"] = "different"
        del self.measurements["samples"][1]["channels"]["APC-A"]
        self.assertTrue({"processing_differs", "channel_sets_differ"}.issubset(self.codes()))

    def test_qc_flags_preserved(self):
        self.measurements["samples"][0]["qc_flags"] = ["ARTIFICIAL upstream warning"]
        self.assertIn("upstream_qc_flags", self.codes())
        self.assertIn("ARTIFICIAL upstream warning", render_report(self.result()))

    def test_required_manifest_fields(self):
        del self.manifest["samples"][0]["plate"]
        with self.assertRaisesRegex(ValidationError, "plate"):
            self.result()

    def test_unknown_manifest_field_rejected(self):
        self.manifest["samples"][0]["conditon"] = "typo"
        with self.assertRaisesRegex(ValidationError, "unknown fields"):
            self.result()

    def test_manifest_field_collision(self):
        self.measurements["samples"][0]["condition"] = "untrusted override"
        with self.assertRaisesRegex(ValidationError, "collision"):
            self.result()

    def test_control_role_strict(self):
        self.manifest["samples"][0]["control_role"] = "probably control"
        with self.assertRaisesRegex(ValidationError, "control_role"):
            self.result()

    def test_concentration_pair_and_numeric_types(self):
        sample = self.manifest["samples"][0]
        sample["concentration"] = 3
        with self.assertRaisesRegex(ValidationError, "together"):
            self.result()
        sample["concentration_unit"] = "nM"
        self.assertEqual(3, self.result()["samples"][0]["concentration"])
        for value in (True, "3", -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "concentration"):
                sample["concentration"] = value
                self.result()

    def test_whitespace_identity_rejected(self):
        self.manifest["samples"][0]["sample_id"] = " synthetic-01 "
        with self.assertRaisesRegex(ValidationError, "whitespace"):
            self.result()

    def test_source_basename_and_digest_validation(self):
        source = self.measurements["samples"][0]["source"]
        for value in ("../private.fcs", "/private/file.fcs", "C:\\private.fcs"):
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "basename"):
                source["basename"] = value
                self.result()
        source["basename"] = "synthetic.csv"
        source["sha256"] = "not a hash"
        with self.assertRaisesRegex(ValidationError, "sha256"):
            self.result()

    def test_html_escaping_all_visible_metadata(self):
        payload = '<script>alert("ARTIFICIAL")</script><img src=x onerror="alert(1)">'
        self.manifest["samples"][0]["condition"] = payload
        self.measurements["samples"][0]["qc_flags"] = [payload]
        self.measurements["samples"][0]["processing"]["label"] = payload
        self.measurements["samples"][0]["channels"][payload] = {"median": 1, "finite_count": 80}
        html = render_report(self.result())
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img ", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("<script src", html)

    def test_demo_only_synthetic_and_no_biology_inferred(self):
        manifest = synthetic_manifest(self.measurements)
        self.assertIsNone(manifest["samples"][0]["biological_replicate"])
        self.assertIn("SYNTHETIC DEMO ONLY", manifest["description"])
        self.measurements["evidence_kind"] = "user_data"
        with self.assertRaisesRegex(ValidationError, "synthetic evidence"):
            synthetic_manifest(self.measurements)

    def test_evidence_mismatch(self):
        self.manifest["evidence_kind"] = "user_data"
        with self.assertRaisesRegex(ValidationError, "evidence_kind"):
            self.result()

    def test_fresh_output_only_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "out"
            write_output(output, self.result())
            original = (output / "experiment.json").read_bytes()
            with self.assertRaisesRegex(ValidationError, "fresh"):
                write_output(output, self.result())
            self.assertEqual(original, (output / "experiment.json").read_bytes())
            link = Path(folder) / "link"
            link.symlink_to(Path(folder) / "does-not-exist", target_is_directory=True)
            with self.assertRaisesRegex(ValidationError, "fresh"):
                write_output(link, self.result())

    def test_json_loader_rejects_duplicate_and_nonfinite_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            for value in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{malformed}'):
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    path.write_text(value, encoding="utf-8")
                    read_json(path)

    def test_overflow_exponent_rejected_after_json_parse(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text(json.dumps(self.measurements).replace('250.0', '1e400'), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "median"):
                analyze(read_json(path), self.manifest)

    def run_cli(self, args):
        environment = dict(os.environ, PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-m", "aureka_flow.workflows.workbench", *args], cwd=ROOT, env=environment, text=True, capture_output=True, timeout=15)

    def test_cli_analyze_and_input_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            measurements, manifest, out = base / "measurements.json", base / "manifest.json", base / "out"
            measurements.write_text(json.dumps(self.measurements), encoding="utf-8")
            manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
            before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (measurements, manifest)]
            args = ["analyze", "--measurements", str(measurements), "--manifest", str(manifest), "--output", str(out)]
            run = self.run_cli(args)
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertEqual({"experiment.json", "report.html"}, {p.name for p in out.iterdir()})
            self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (measurements, manifest)])
            rerun = self.run_cli(args)
            self.assertNotEqual(0, rerun.returncode)
            self.assertNotIn("Traceback", rerun.stderr)

    def test_cli_demo_and_user_data_refusal(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            measurements = base / "measurements.json"
            measurements.write_text(json.dumps(self.measurements), encoding="utf-8")
            run = self.run_cli(["demo", "--measurements", str(measurements), "--output", str(base / "out")])
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertTrue((base / "out" / "synthetic-manifest.json").is_file())
            self.measurements["evidence_kind"] = "user_data"
            measurements.write_text(json.dumps(self.measurements), encoding="utf-8")
            run = self.run_cli(["demo", "--measurements", str(measurements), "--output", str(base / "refused")])
            self.assertNotEqual(0, run.returncode)
            self.assertFalse((base / "refused").exists())

    def test_cli_invalid_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            path = base / "bad.json"
            path.write_text('{"bad":NaN}', encoding="utf-8")
            run = self.run_cli(["demo", "--measurements", str(path), "--output", str(base / "out")])
            self.assertNotEqual(0, run.returncode)
            self.assertNotIn("Traceback", run.stderr)
            self.assertFalse((base / "out").exists())


if __name__ == "__main__":
    unittest.main()
