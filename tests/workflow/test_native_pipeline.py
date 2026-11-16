"""Generated synthetic FCS through the whole workflow, plus QC-receipt regressions.

No laboratory files are used. Native cases skip without the optional flow runtime.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


from aureka_flow.workflows.core.core import summarize_events
from aureka_flow.workflows.workbench.validation import measurements, ValidationError
from aureka_flow.workflows.pipeline import run_batch


def config(sample_id="synthetic-a", gated=True):
    document = {
        "schema_version": "yeast-facs-analysis-config/v1",
        "sample_id": sample_id,
        "evidence_kind": "synthetic",
        "channels": ["FITC-A", "APC-A"],
        "compensation": {"state": "uncompensated", "reason": "Synthetic test values"},
    }
    if gated:
        document["rectangle_gates"] = [{
            "gate_id": "synthetic-reference",
            "scope": "exploratory",
            "reference_status": "Synthetic-only rectangle, not a biological gate",
            "bounds": {"FITC-A": {"min": 0, "max": 9}},
        }]
    return document


def masked_measurements(gated=False):
    mask = {
        "schema_version": "yeast-facs-qc-mask/v1", "source_sha256": "0" * 64,
        "event_count": 4, "kept_original_event_indices": [0, 2, 3],
        "method": "Synthetic external mask; no upstream QC algorithm executed",
    }
    return summarize_events(
        [[-4, 2, 0], [2, 8, 10], [6, 14, 20], [10, 20, 30]],
        ["FITC-A", "APC-A", "Time"], config(gated=gated),
        source={"basename": "synthetic.fcs", "sha256": "0" * 64}, qc_mask=mask,
    )


class ExternalQCReceiptValidationTests(unittest.TestCase):
    def test_valid_ungated_qc_only_selection(self):
        data = masked_measurements()
        sample = measurements(data)[0]
        self.assertEqual(sample["gate_status"], "ungated")
        self.assertEqual(sample["selected_count"], 3)
        self.assertEqual(sample["processing"]["selection"], "external_qc_mask_only")

    def test_valid_qc_rectangle_intersection(self):
        sample = measurements(masked_measurements(gated=True))[0]
        self.assertEqual(sample["selected_count"], 1)
        self.assertEqual(sample["processing"]["selected_event_ranges"], [[2, 3]])

    def test_plain_ungated_dropped_count_still_rejected(self):
        data = masked_measurements()
        data["samples"][0]["processing"]["external_qc_mask"] = None
        with self.assertRaisesRegex(ValidationError, "ungated"):
            measurements(data)

    def test_external_mask_hash_and_counts_are_bound(self):
        for field, value in (("source_sha256", "1" * 64), ("original_event_count", True),
                             ("original_event_count", 5), ("kept_event_count", 2),
                             ("execution", "PeacoQC_executed_here"), ("method_attribution", "")):
            with self.subTest(field=field):
                data = masked_measurements()
                data["samples"][0]["processing"]["external_qc_mask"][field] = value
                with self.assertRaises(ValidationError):
                    measurements(data)

    def test_external_mask_ranges_reject_bad_original_indices(self):
        for ranges in ([[0, 3], [2, 4]], [[2, 4], [0, 1]], [[0, 5]],
                       [[False, 1]], [[-1, 2]], [[0, 1.5]], [[0, 0]], [[0]]):
            with self.subTest(ranges=ranges):
                data = masked_measurements()
                data["samples"][0]["processing"]["external_qc_mask"]["kept_original_event_ranges"] = ranges
                with self.assertRaises(ValidationError):
                    measurements(data)

    def test_selected_ranges_must_be_a_mask_subset(self):
        data = masked_measurements(gated=True)
        data["samples"][0]["processing"]["selected_event_ranges"] = [[1, 2]]
        with self.assertRaisesRegex(ValidationError, "subset"):
            measurements(data)

    def test_all_stage_counts_checked(self):
        for field in ("input", "after_external_qc_mask", "after_supplied_rectangles"):
            data = masked_measurements()
            data["samples"][0]["processing"]["stage_counts"][field] = 99
            with self.subTest(field=field), self.assertRaises(ValidationError):
                measurements(data)

    def test_original_index_semantics_required(self):
        data = masked_measurements()
        data["samples"][0]["processing"]["event_identity"] = "renumbered_subset"
        with self.assertRaisesRegex(ValidationError, "original event-index"):
            measurements(data)

    def test_ungated_may_not_drop_additional_mask_kept_events(self):
        data = masked_measurements()
        sample = data["samples"][0]
        sample["selected_count"] = 2
        sample["processing"]["selected_event_ranges"] = [[2, 4]]
        sample["processing"]["stage_counts"]["after_supplied_rectangles"] = 2
        for channel in sample["channels"].values():
            channel["finite_count"] = 2
        with self.assertRaisesRegex(ValidationError, "retain every"):
            measurements(data)

    def test_empty_qc_selection_is_valid_not_all_events(self):
        data = masked_measurements()
        sample = data["samples"][0]
        sample["selected_count"] = 0
        sample["processing"]["selected_event_ranges"] = []
        sample["processing"]["stage_counts"].update(after_external_qc_mask=0, after_supplied_rectangles=0)
        mask = sample["processing"]["external_qc_mask"]
        mask.update(kept_event_count=0, kept_original_event_ranges=[])
        for channel in sample["channels"].values():
            channel.update(finite_count=0, median=None)
        self.assertEqual(measurements(data)[0]["selected_count"], 0)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


@unittest.skipUnless(importlib.util.find_spec("flowkit") and importlib.util.find_spec("flowio"),
                     "optional FlowKit/FlowIO runtime absent")
class NativePipelineTests(unittest.TestCase):
    def make_inputs(self, root, *, gated=True, sortseq=False, cross_batch=False):
        import flowio

        records = []
        manifest = {"schema_version": "yeast-facs-samples/v1", "evidence_kind": "synthetic", "samples": []}
        events = [
            [-4, 2, 0, 2, 8, 10, 6, 14, 20, 10, 20, 30],
            [-6, 4, 0, 4, 10, 10, 8, 20, 20, 16, 24, 30],
        ]
        for index, letter in enumerate(("a", "b")):
            sample_id = f"synthetic-{letter}"
            fcs = root / (sample_id + ".fcs")
            with fcs.open("wb") as handle:
                flowio.create_fcs(handle, events[index], ["FITC-A", "APC-A", "Time"],
                                 metadata_dict={"btim": "12:00:00", "etim": "12:00:03", "timestep": "0.1",
                                                "spillover": "2,FITC-A,APC-A,1,0.5,0,1"})
            cfg = config(sample_id, gated)
            cfg["compensation"] = {"state": "embedded", "reason": "Synthetic known nonidentity spillover matrix"}
            cfg_file = root / (sample_id + ".json")
            write_json(cfg_file, cfg)
            record = {"fcs": fcs.name, "config": cfg_file.name}
            if letter == "a":
                mask = {"schema_version": "yeast-facs-qc-mask/v1",
                        "source_sha256": hashlib.sha256(fcs.read_bytes()).hexdigest(),
                        "event_count": 4, "kept_original_event_indices": [0, 2, 3],
                        "method": "Synthetic external mask; no PeacoQC execution"}
                write_json(root / "mask.json", mask)
                record["qc_mask"] = "mask.json"
            records.append(record)
            manifest["samples"].append({
                "sample_id": sample_id, "condition": "synthetic-condition", "biological_replicate": None,
                "batch_id": f"synthetic-batch-{letter}" if cross_batch else "synthetic-batch",
                "plate": "synthetic-plate", "well": f"A{index + 1}", "control_role": "sample",
            })
        write_json(root / "samples.json", manifest)
        spec = {"schema_version": "yeast-facs-run/v1", "files": records, "sample_manifest": "samples.json"}
        if sortseq:
            bins = {"schema_version": "yeast-sort-bins/v1", "evidence_kind": "synthetic", "bins": []}
            counts = {"schema_version": "yeast-variant-counts/v1", "evidence_kind": "synthetic", "counts": []}
            for index, letter in enumerate(("a", "b")):
                seq = f"synthetic-seq-{letter}"
                bins["bins"].append({"bin_id": f"synthetic-bin-{letter}", "sample_id": f"synthetic-{letter}",
                                     "sequencing_sample_id": seq, "sorted_events": 100 * (index + 1),
                                     "gate_definition_id": "synthetic-reference"})
                for variant, count in zip(("v1", "v2"), (10, 30) if index == 0 else (0, 20)):
                    counts["counts"].append({"sequencing_sample_id": seq, "variant_id": "synthetic-" + variant, "read_count": count})
            write_json(root / "bins.json", bins)
            write_json(root / "counts.json", counts)
            spec.update(sort_bins="bins.json", variant_counts="counts.json")
        write_json(root / "run.json", spec)
        return root / "run.json"

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_full_native_pipeline_qc_compensation_gates_sortseq_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_file = self.make_inputs(root, sortseq=True)
            original_inputs = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
            output = root / "result"
            receipt = run_batch(run_file, output)
            measurement = self.read(output / "measurements.json")
            sample_a, sample_b = measurement["samples"]
            self.assertEqual(sample_a["selected_count"], 1)
            self.assertEqual(sample_a["processing"]["selected_event_ranges"], [[2, 3]])
            self.assertEqual(sample_a["channels"]["APC-A"]["median"], 11)
            self.assertEqual(sample_b["selected_count"], 2)
            self.assertEqual(sample_b["channels"]["APC-A"]["median"], 12)
            self.assertTrue(sample_a["processing"]["engine"].startswith("FlowKit/"))
            self.assertEqual(sample_a["processing"]["external_qc_mask"]["execution"], "external_not_executed_by_this_package")
            self.assertNotIn("time_scale_clock_mismatch", sample_a["qc_flags"])
            experiment = self.read(output / "05-report" / "experiment.json")
            self.assertEqual(experiment["summary"]["acquired_event_count_sum"], 8)
            self.assertEqual(experiment["summary"]["selected_event_count_sum"], 3)
            self.assertEqual(experiment["comparison_status"], "metadata_limited")
            linked = self.read(output / "06-sortseq" / "linked_counts.json")
            self.assertEqual(linked["analysis_status"], "descriptive_linkage_only")
            self.assertEqual(linked["upstream_comparison_status"], "metadata_limited")
            self.assertEqual([row["read_fraction_within_sequencing_sample"] for row in linked["linked_counts"]], [0.25, 0.75, 0, 1])
            self.assertEqual(linked["bins"][0]["sorted_events"], 100)
            self.assertEqual(linked["bins"][0]["total_reads"], 40)
            self.assertIn("external_qc_mask_user_supplied_not_independently_validated", linked["bins"][0]["upstream_qc_flags"])
            self.assertEqual(receipt["evidence_kind"], "synthetic")
            self.assertFalse(receipt["biological_validation"])
            self.assertEqual({row["id"] for row in receipt["modules"]}, {"ingest", "qc", "gating", "experiment", "report", "sortseq"})
            self.assertIn("external QC masks", receipt["upstream_integration_scope"])
            self.assertEqual(self.read(output / "run-receipt.json"), receipt)
            for item in receipt["files"]:
                path = Path(item["path"])
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertEqual(hashlib.sha256((output / path).read_bytes()).hexdigest(), item["sha256"])
            for name, original in original_inputs.items():
                self.assertEqual((root / name).read_bytes(), original)
            for path in output.rglob("*.json"):
                self.assertNotIn(str(root), path.read_text())

    def test_native_qc_mask_without_fluorescence_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = run_batch(self.make_inputs(root, gated=False), root / "result")
            sample = self.read(root / "result" / "measurements.json")["samples"][0]
            self.assertEqual(sample["gate_status"], "ungated")
            self.assertEqual(sample["selected_count"], 3)
            self.assertEqual(sample["processing"]["selection"], "external_qc_mask_only")
            self.assertEqual(sample["processing"]["selected_event_ranges"], [[0, 1], [2, 4]])
            self.assertEqual(next(row for row in receipt["modules"] if row["id"] == "sortseq")["status"], "not_run")
            self.assertFalse((root / "result" / "06-sortseq").exists())

    def test_invalid_mask_rejected_before_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_file = self.make_inputs(root)
            mask = self.read(root / "mask.json")
            mask["source_sha256"] = "1" * 64
            write_json(root / "mask.json", mask)
            with self.assertRaisesRegex(ValueError, "source_sha256"):
                run_batch(run_file, root / "result")
            self.assertFalse((root / "result").exists())

    def test_duplicate_fcs_contents_rejected_before_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_file = self.make_inputs(root)
            (root / "synthetic-b.fcs").write_bytes((root / "synthetic-a.fcs").read_bytes())
            with self.assertRaisesRegex(ValueError, "duplicate FCS content"):
                run_batch(run_file, root / "result")
            self.assertFalse((root / "result").exists())

    def test_cross_batch_restriction_propagates_to_sortseq(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = run_batch(self.make_inputs(root, sortseq=True, cross_batch=True), root / "result")
            self.assertEqual(receipt["comparison_status"], "cross_batch_blocked")
            linked = self.read(root / "result" / "06-sortseq" / "linked_counts.json")
            self.assertEqual(linked["upstream_comparison_status"], "cross_batch_blocked")

    def test_invalid_sort_mapping_has_no_partial_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_file = self.make_inputs(root, sortseq=True)
            bins = self.read(root / "bins.json")
            bins["bins"][0]["sample_id"] = "not-an-input-sample"
            write_json(root / "bins.json", bins)
            with self.assertRaisesRegex(ValueError, "unknown sample_id"):
                run_batch(run_file, root / "result")
            self.assertFalse((root / "result").exists())

    def test_existing_result_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_file = self.make_inputs(root)
            output = root / "result"
            run_batch(run_file, output)
            before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "fresh nonexistent"):
                run_batch(run_file, output)
            after = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
