"""Synthetic orchestration tests. Mocked FCS inputs are NOT real cytometry data.

Native decoding is replaced only in batch tests; the real core summary, joins,
HTML generation, linkage, serializers and receipt hashing still execute.
"""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aureka_flow.workflows.core.core import summarize_events
from aureka_flow.workflows import pipeline
from aureka_flow.workflows.cli import main as cli_main


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-pipeline-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.inputs = self.base / "artificial-inputs"
        self.inputs.mkdir()
        self.output = self.base / "output"

    def save(self, name, data):
        path = self.inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
        return path

    def load(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def make_run(self, count=2, *, evidence_kind="synthetic", with_sort=False):
        rows, records = [], []
        for index in range(count):
            sid = f"synthetic-sample-{index + 1}"
            fcs = self.inputs / f"synthetic-{index + 1}.fcs"
            fcs.write_bytes(f"ARTIFICIAL MOCK INPUT, NOT VALID FCS: {index + 1}\n".encode())
            config = {
                "schema_version": "yeast-facs-analysis-config/v1",
                "sample_id": sid,
                "evidence_kind": evidence_kind,
                "channels": ["FITC-A", "APC-A"],
                "compensation": {"state": "uncompensated", "reason": "Synthetic orchestration fixture; no spillover model"},
            }
            config_path = self.save(f"config-{index + 1}.json", config)
            records.append({"fcs": fcs.name, "config": config_path.name})
            rows.append({"sample_id": sid, "condition": "synthetic-condition", "biological_replicate": f"synthetic-bio-{index + 1}", "batch_id": "synthetic-batch", "plate": None, "well": None, "control_role": "sample"})
        manifest = {"schema_version": "yeast-facs-samples/v1", "evidence_kind": evidence_kind, "samples": rows}
        self.save("samples.json", manifest)
        spec = {"schema_version": "yeast-facs-run/v1", "files": records, "sample_manifest": "samples.json"}
        if with_sort:
            bins = {"schema_version": "yeast-sort-bins/v1", "evidence_kind": evidence_kind, "bins": [{"bin_id": "synthetic-bin", "sample_id": rows[0]["sample_id"], "sequencing_sample_id": "synthetic-seq", "sorted_events": 100, "gate_definition_id": "illustration-only"}]}
            counts = {"schema_version": "yeast-variant-counts/v1", "evidence_kind": evidence_kind, "counts": [{"sequencing_sample_id": "synthetic-seq", "variant_id": "synthetic-v1", "read_count": 3}, {"sequencing_sample_id": "synthetic-seq", "variant_id": "synthetic-v2", "read_count": 1}]}
            self.save("bins.json", bins)
            self.save("counts.json", counts)
            spec.update(sort_bins="bins.json", variant_counts="counts.json")
        return self.save("run.json", spec)

    @staticmethod
    def fake_decoder(path, config, *, qc_mask=None):
        """Fake only FCS I/O, but execute genuine downstream core calculations."""
        path = Path(path)
        source = {"basename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return summarize_events(
            [[1.0, -2.0, 0.0], [5.0, 6.0, 1.0]], ["FITC-A", "APC-A", "Time"], config,
            source=source, metadata={"timestep": "1", "btim": "12:00:00", "etim": "12:00:01"},
            engine="synthetic_orchestration_mock_not_native_FCS", qc_mask=qc_mask,
        )

    def digest_inputs(self):
        return {str(path.relative_to(self.inputs)): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.inputs.rglob("*") if path.is_file()}

    def assert_receipt(self, output, receipt):
        persisted = self.load(output / "run-receipt.json")
        self.assertEqual(receipt, persisted)
        self.assertEqual("yeast-facs-run-receipt/v1", receipt["schema_version"])
        self.assertFalse(receipt["biological_validation"])
        expected = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()} - {"run-receipt.json"}
        recorded = [entry["path"] for entry in receipt["files"]]
        self.assertEqual(len(recorded), len(set(recorded)))
        self.assertEqual(expected, set(recorded))
        for entry in receipt["files"]:
            relative = Path(entry["path"])
            self.assertFalse(relative.is_absolute())
            self.assertNotIn("..", relative.parts)
            self.assertEqual(hashlib.sha256((output / relative).read_bytes()).hexdigest(), entry["sha256"])

    def run_cli_subprocess(self, args):
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-B", "-m", "aureka_flow.workflows", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)

    def test_full_six_module_demo(self):
        receipt = pipeline.demo_run(self.output)
        self.assertEqual("synthetic", receipt["evidence_kind"])
        self.assertEqual(3, receipt["sample_records"])
        self.assertEqual({"ingest", "qc", "gating", "experiment", "report", "sortseq"}, {row["id"] for row in receipt["modules"]})
        self.assertNotIn("not_run", {row["status"] for row in receipt["modules"]})
        experiment = self.load(self.output / "05-report" / "experiment.json")
        linkage = self.load(self.output / "06-sortseq" / "linked_counts.json")
        self.assertEqual("yeast-facs-experiment/v1", experiment["schema_version"])
        self.assertEqual("descriptive_linkage_only", linkage["analysis_status"])
        self.assertEqual(experiment["comparison_status"], linkage["upstream_comparison_status"])
        self.assertEqual(experiment["warnings"], linkage["upstream_warnings"])
        self.assertEqual(12, len(linkage["linked_counts"]))
        self.assertTrue((self.output / "06-sortseq" / "synthetic_sort_bins.json").is_file())
        self.assertTrue((self.output / "06-sortseq" / "synthetic_variant_counts.json").is_file())
        self.assert_receipt(self.output, receipt)

    def test_demo_receipt_hashes_are_exact_and_complete(self):
        receipt = pipeline.demo_run(self.output)
        self.assert_receipt(self.output, receipt)
        self.assertNotIn("run-receipt.json", {row["path"] for row in receipt["files"]})

    def test_demo_repeat_refused_without_changing_existing_files(self):
        pipeline.demo_run(self.output)
        before = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "fresh"):
            pipeline.demo_run(self.output)
        self.assertEqual(before, {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob("*") if p.is_file()})

    def test_existing_file_and_dangling_symlink_refused(self):
        self.output.write_text("SYNTHETIC SENTINEL", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fresh"):
            pipeline.demo_run(self.output)
        self.assertEqual("SYNTHETIC SENTINEL", self.output.read_text(encoding="utf-8"))
        link = self.base / "dangling-output"
        target = self.base / "must-not-create"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "fresh"):
            pipeline.demo_run(link)
        self.assertFalse(target.exists())

    def test_mocked_multi_file_batch_preserves_joined_samples_and_sources(self):
        run = self.make_run()
        before = self.digest_inputs()
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder) as native:
            receipt = pipeline.run_batch(run, self.output)
        self.assertEqual(2, native.call_count)
        self.assertEqual(before, self.digest_inputs())
        self.assertEqual(2, receipt["sample_records"])
        self.assertEqual("not_run", next(row["status"] for row in receipt["modules"] if row["id"] == "sortseq"))
        experiment = self.load(self.output / "05-report" / "experiment.json")
        self.assertEqual(["synthetic-sample-1", "synthetic-sample-2"], [s["sample_id"] for s in experiment["samples"]])
        for sample in experiment["samples"]:
            self.assertEqual(2, sample["event_count"])
            self.assertEqual(2, sample["selected_count"])
            self.assertEqual(3.0, sample["channels"]["FITC-A"]["median"])
            self.assertEqual(2.0, sample["channels"]["APC-A"]["median"])
            self.assertEqual("synthetic-condition", sample["condition"])
            self.assertEqual(before[sample["source"]["basename"]], sample["source"]["sha256"])
        self.assertFalse((self.output / "06-sortseq").exists())
        self.assert_receipt(self.output, receipt)
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(str(self.base), path.read_text(encoding="utf-8"))

    def test_batch_optional_sort_inputs_linked_without_invented_synthetic_files(self):
        run = self.make_run(with_sort=True)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder):
            receipt = pipeline.run_batch(run, self.output)
        linkage = self.load(self.output / "06-sortseq" / "linked_counts.json")
        self.assertEqual([0.75, 0.25], [row["read_fraction_within_sequencing_sample"] for row in linkage["linked_counts"]])
        self.assertFalse((self.output / "06-sortseq" / "synthetic_sort_bins.json").exists())
        self.assertEqual("descriptive_linkage", next(row["status"] for row in receipt["modules"] if row["id"] == "sortseq"))
        self.assert_receipt(self.output, receipt)

    def test_sort_files_must_be_supplied_together(self):
        run = self.make_run(with_sort=True)
        original = self.load(run)
        for absent in ("sort_bins", "variant_counts"):
            with self.subTest(absent=absent):
                spec = deepcopy(original)
                del spec[absent]
                self.save("run.json", spec)
                with patch.object(pipeline, "analyze_fcs") as native, self.assertRaisesRegex(ValueError, "together"):
                    pipeline.run_batch(run, self.output)
                native.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_duplicate_fcs_path_rejected(self):
        run = self.make_run()
        spec = self.load(run)
        spec["files"][1]["fcs"] = "./" + spec["files"][0]["fcs"]
        self.save("run.json", spec)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder) as native, self.assertRaisesRegex(ValueError, "same FCS path"):
            pipeline.run_batch(run, self.output)
        self.assertEqual(1, native.call_count)
        self.assertFalse(self.output.exists())

    def test_duplicate_fcs_symlink_path_rejected(self):
        run = self.make_run()
        (self.inputs / "synthetic-link.fcs").symlink_to(self.inputs / "synthetic-1.fcs")
        spec = self.load(run)
        spec["files"][1]["fcs"] = "synthetic-link.fcs"
        self.save("run.json", spec)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), self.assertRaisesRegex(ValueError, "same FCS path"):
            pipeline.run_batch(run, self.output)
        self.assertFalse(self.output.exists())

    def test_duplicate_fcs_content_rejected_even_with_different_paths_and_ids(self):
        run = self.make_run()
        (self.inputs / "synthetic-2.fcs").write_bytes((self.inputs / "synthetic-1.fcs").read_bytes())
        before = self.digest_inputs()
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder) as native, self.assertRaisesRegex(ValueError, "duplicate FCS content"):
            pipeline.run_batch(run, self.output)
        self.assertEqual(2, native.call_count)
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.digest_inputs())

    def test_mixed_evidence_rejected(self):
        run = self.make_run()
        config = self.load(self.inputs / "config-2.json")
        config["evidence_kind"] = "user_data"  # Intentionally contradictory synthetic fixture.
        self.save("config-2.json", config)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), self.assertRaisesRegex(ValueError, "cannot mix"):
            pipeline.run_batch(run, self.output)
        self.assertFalse(self.output.exists())

    def test_sort_evidence_mismatch_rejected_before_output(self):
        run = self.make_run(with_sort=True)
        counts = self.load(self.inputs / "counts.json")
        counts["evidence_kind"] = "user_data"  # Deliberately false label; no real data.
        self.save("counts.json", counts)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), self.assertRaisesRegex(ValueError, "evidence_kind"):
            pipeline.run_batch(run, self.output)
        self.assertFalse(self.output.exists())

    def test_invalid_sample_join_leaves_no_output(self):
        run = self.make_run()
        manifest = self.load(self.inputs / "samples.json")
        manifest["samples"][1]["sample_id"] = "unmatched-artificial-id"
        self.save("samples.json", manifest)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), self.assertRaisesRegex(ValueError, "sample_id join"):
            pipeline.run_batch(run, self.output)
        self.assertFalse(self.output.exists())

    def test_duplicate_sample_ids_from_configs_rejected_before_output(self):
        run = self.make_run()
        config = self.load(self.inputs / "config-2.json")
        config["sample_id"] = "synthetic-sample-1"
        self.save("config-2.json", config)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), self.assertRaisesRegex(ValueError, "duplicate ID"):
            pipeline.run_batch(run, self.output)
        self.assertFalse(self.output.exists())

    def test_run_schema_unknown_fields_and_empty_files_rejected_without_output(self):
        run = self.make_run()
        original = self.load(run)
        cases = [dict(original, schema_version=True), dict(original, unexpected="value"), dict(original, files=[]), dict(original, files="not-array"), {"schema_version": "yeast-facs-run/v1"}]
        for index, spec in enumerate(cases):
            with self.subTest(index=index):
                self.save("run.json", spec)
                with patch.object(pipeline, "analyze_fcs") as native, self.assertRaises(ValueError):
                    pipeline.run_batch(run, self.output)
                native.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_invalid_file_record_unknown_field_and_missing_config(self):
        run = self.make_run()
        original = self.load(run)
        cases = [{"fcs": "synthetic-1.fcs"}, {"fcs": "synthetic-1.fcs", "config": "config-1.json", "extra": "ignored?"}]
        for record in cases:
            with self.subTest(record=record):
                spec = deepcopy(original)
                spec["files"] = [record]
                self.save("run.json", spec)
                with patch.object(pipeline, "analyze_fcs") as native, self.assertRaises(ValueError):
                    pipeline.run_batch(run, self.output)
                native.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_missing_input_file_leaves_no_output(self):
        run = self.make_run()
        spec = self.load(run)
        spec["files"][0]["fcs"] = "does-not-exist.fcs"
        self.save("run.json", spec)
        with patch.object(pipeline, "analyze_fcs") as native, self.assertRaisesRegex(ValueError, "not found"):
            pipeline.run_batch(run, self.output)
        native.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_invalid_sort_join_leaves_no_output(self):
        run = self.make_run(with_sort=True)
        bins = self.load(self.inputs / "bins.json")
        bins["bins"][0]["sample_id"] = "unknown-artificial-sample"
        self.save("bins.json", bins)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), self.assertRaisesRegex(ValueError, "unknown sample_id"):
            pipeline.run_batch(run, self.output)
        self.assertFalse(self.output.exists())

    def test_fresh_output_rejected_before_native_work(self):
        run = self.make_run()
        self.output.mkdir()
        sentinel = self.output / "sentinel.txt"
        sentinel.write_text("KEEP ARTIFICIAL", encoding="utf-8")
        with patch.object(pipeline, "analyze_fcs") as native, self.assertRaisesRegex(ValueError, "fresh"):
            pipeline.run_batch(run, self.output)
        native.assert_not_called()
        self.assertEqual([sentinel], list(self.output.iterdir()))
        self.assertEqual("KEEP ARTIFICIAL", sentinel.read_text(encoding="utf-8"))

    def test_external_qc_mask_forwarded_as_keyword_and_preserved(self):
        run = self.make_run(count=1)
        source = self.inputs / "synthetic-1.fcs"
        mask = {"schema_version": "yeast-facs-qc-mask/v1", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "event_count": 2, "kept_original_event_indices": [1], "method": "synthetic reviewed mask, not a real upstream tool execution"}
        self.save("mask.json", mask)
        spec = self.load(run)
        spec["files"][0]["qc_mask"] = "mask.json"
        self.save("run.json", spec)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder) as native:
            pipeline.run_batch(run, self.output)
        self.assertEqual(mask, native.call_args.kwargs["qc_mask"])
        sample = self.load(self.output / "05-report" / "experiment.json")["samples"][0]
        self.assertEqual(1, sample["selected_count"])
        self.assertEqual(2, sample["event_count"])
        self.assertEqual([[1, 2]], sample["processing"]["selected_event_ranges"])
        self.assertEqual(1, sample["processing"]["stage_counts"]["after_external_qc_mask"])

    def test_external_qc_mask_source_mismatch_leaves_no_output(self):
        run = self.make_run(count=1)
        mask = {"schema_version": "yeast-facs-qc-mask/v1", "source_sha256": "0" * 64, "event_count": 2, "kept_original_event_indices": [1], "method": "artificial"}
        self.save("mask.json", mask)
        spec = self.load(run)
        spec["files"][0]["qc_mask"] = "mask.json"
        self.save("run.json", spec)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), self.assertRaisesRegex(ValueError, "source_sha256"):
            pipeline.run_batch(run, self.output)
        self.assertFalse(self.output.exists())

    def test_nonfinite_serialization_refused_before_output(self):
        measurements = pipeline.measurement_demo()
        manifest = pipeline.synthetic_manifest(measurements)
        experiment = pipeline.analyze(measurements, manifest)
        experiment["bad_metadata"] = float("nan")
        with self.assertRaises(ValueError):
            pipeline.write_run(self.output, measurements, manifest, experiment, None)
        self.assertFalse(self.output.exists())

    def test_mocked_batch_cli_and_input_integrity(self):
        run = self.make_run()
        before = self.digest_inputs()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder), redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli_main(["run", "--manifest", str(run), "--output", str(self.output)])
        self.assertEqual(0, code, stderr.getvalue())
        self.assertEqual("synthetic", json.loads(stdout.getvalue())["evidence_kind"])
        self.assertEqual(before, self.digest_inputs())
        self.assertTrue((self.output / "index.html").is_file())

    def test_cli_invalid_json_has_error_no_traceback_or_output(self):
        run = self.inputs / "malformed.json"
        run.write_text('{"schema_version": NaN}', encoding="utf-8")
        result = self.run_cli_subprocess(["run", "--manifest", str(run), "--output", str(self.output)])
        self.assertNotEqual(0, result.returncode)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.output.exists())

    def test_cli_demo_runs_without_optional_dependency(self):
        result = self.run_cli_subprocess(["demo", "--output", str(self.output)])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("synthetic", json.loads(result.stdout)["evidence_kind"])
        self.assert_receipt(self.output, self.load(self.output / "run-receipt.json"))
        repeat = self.run_cli_subprocess(["demo", "--output", str(self.output)])
        self.assertNotEqual(0, repeat.returncode)
        self.assertNotIn("Traceback", repeat.stderr)

    def test_cli_lists_six_modules(self):
        result = self.run_cli_subprocess(["modules"])
        self.assertEqual(0, result.returncode, result.stderr)
        modules = json.loads(result.stdout)
        self.assertEqual(6, len(modules))
        self.assertEqual(6, len({m["id"] for m in modules}))

    def test_cli_component_forwarding_help(self):
        for command in ("core", "workbench", "sortseq"):
            with self.subTest(command=command):
                result = self.run_cli_subprocess([command, "--help"])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_html_injection_remains_escaped_after_full_batch(self):
        run = self.make_run()
        manifest = self.load(self.inputs / "samples.json")
        payload = '<script>alert("ARTIFICIAL")</script>'
        manifest["samples"][0]["condition"] = payload
        self.save("samples.json", manifest)
        with patch.object(pipeline, "analyze_fcs", side_effect=self.fake_decoder):
            pipeline.run_batch(run, self.output)
        report = (self.output / "05-report" / "report.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("Content-Security-Policy", report)
        self.assertIn("Content-Security-Policy", (self.output / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
