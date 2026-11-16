"""Gallery fixtures are invented; only the real software contracts are exercised."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("gallery_synthetic_data", ROOT / "examples" / "workflows" / "gallery" / "synthetic_data.py")
gallery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gallery)

from aureka_flow.workflows.workbench.analysis import analyze
from aureka_flow.workflows.sortseq.linkage import link_experiment


class GalleryParameterTests(unittest.TestCase):
    def test_invalid_seed(self):
        for seed in (True, -1, 2**64, 1.2, "1", None):
            with self.subTest(seed=seed), self.assertRaisesRegex(ValueError, "seed"):
                gallery.build_dataset(seed=seed)

    def test_invalid_event_count(self):
        for count in (False, -1, 0, 99, 100001, 100.5, "3000", None):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "events_per_sample"):
                gallery.build_dataset(events_per_sample=count)


@unittest.skipUnless(importlib.util.find_spec("numpy"), "optional NumPy gallery dependency absent")
class GalleryDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.data = gallery.build_dataset()

    def test_exact_return_shape_and_synthetic_provenance(self):
        self.assertEqual(set(self.data), {"metadata", "samples", "detectors", "measurements", "manifest", "experiment", "sort_bins", "variant_counts", "linked"})
        self.assertEqual(len(self.data["samples"]), 9)
        self.assertEqual(self.data["detectors"], ["FSC-A", "SSC-A", "FITC-A", "APC-A", "Time"])
        metadata = self.data["metadata"]
        self.assertEqual(metadata["conditions"], ["Baseline", "Shift A", "Shift B"])
        self.assertEqual(metadata["real_data_sources"], [])
        self.assertEqual(metadata["real_biological_replicates"], 0)
        self.assertFalse(metadata["experimental_measurements"])
        self.assertIn("PeacoQC", metadata["not_executed"])
        self.assertIn("not automatically discovered", metadata["qc_mask_semantics"])
        for key in ("measurements", "manifest", "experiment", "sort_bins", "variant_counts", "linked"):
            self.assertEqual(self.data[key]["evidence_kind"], "synthetic")

    def test_finite_shapes_positive_correlated_scatter(self):
        for sample in self.data["samples"]:
            events = sample["events"]
            self.assertEqual(events.shape, (3000, 5))
            self.assertTrue(self.np.isfinite(events).all())
            self.assertTrue((events[:, :2] > 0).all())
            self.assertGreater(self.np.corrcoef(self.np.log(events[:, 0]), self.np.log(events[:, 1]))[0, 1], 0.6)
            self.assertEqual(sample["qc_mask"].dtype, self.np.dtype(bool))
            self.assertEqual(sample["selected_mask"].dtype, self.np.dtype(bool))
            self.assertGreater((events[:, 2] < 400).sum(), 100)

    def test_predetermined_mask_and_expression_only_selection(self):
        for sample in self.data["samples"]:
            event = sample["events"]
            expected_qc = ~((event[:, 4] >= 80) & (event[:, 4] < 100))
            self.np.testing.assert_array_equal(sample["qc_mask"], expected_qc)
            self.np.testing.assert_array_equal(sample["selected_mask"], expected_qc & (event[:, 2] >= 400))
            self.assertTrue((~expected_qc).any())
            self.assertTrue(sample["selected_mask"].any())

    def test_pipeline_original_indices_and_medians(self):
        by_id = {sample["sample_id"]: sample for sample in self.data["samples"]}
        for measured in self.data["measurements"]["samples"]:
            original = by_id[measured["sample_id"]]
            selected = original["selected_mask"]
            indices = [index for start, end in measured["processing"]["selected_event_ranges"] for index in range(start, end)]
            self.assertEqual(indices, self.np.flatnonzero(selected).tolist())
            self.assertEqual(measured["selected_count"], int(selected.sum()))
            self.assertEqual(measured["event_count"], 3000)
            self.assertEqual(measured["processing"]["external_qc_mask"]["kept_event_count"], int(original["qc_mask"].sum()))
            self.assertEqual(set(measured["processing"]["gates"][0]["bounds"]), {"FITC-A"})
            self.assertEqual(measured["channels"]["APC-A"]["finite_count"], int(selected.sum()))
            self.assertAlmostEqual(measured["channels"]["APC-A"]["median"], float(self.np.median(original["events"][selected, 3])))
            self.assertNotIn("time_scale_clock_mismatch", measured["qc_flags"])

    def test_condition_shifts_are_programmed_and_visible(self):
        medians = []
        for condition in gallery.CONDITIONS:
            values = [sample["events"][sample["selected_mask"], 3]
                      for sample in self.data["samples"] if sample["condition"] == condition]
            medians.append(float(self.np.median(self.np.concatenate(values))))
        self.assertTrue(40 < medians[0] < 120)
        self.assertTrue(150 < medians[1] < 400)
        self.assertTrue(600 < medians[2] < 1400)
        self.assertGreater(medians[1] / medians[0], 2)
        self.assertGreater(medians[2] / medians[1], 2)

    def test_injected_transient_is_visible_but_not_detected_by_algorithm(self):
        for sample in self.data["samples"]:
            events = sample["events"]
            transient_values = events[~sample["qc_mask"], 3]
            ordinary_values = events[sample["qc_mask"], 3]
            self.assertGreater(float(self.np.median(transient_values)), 1.8 * float(self.np.median(ordinary_values)))
        self.assertFalse(self.data["metadata"]["generation_parameters"]["external_qc_mask"]["PeacoQC_executed"])

    def test_source_hash_is_documented_array_serialization(self):
        by_id = {sample["sample_id"]: sample for sample in self.data["samples"]}
        for measured in self.data["measurements"]["samples"]:
            values = by_id[measured["sample_id"]]["events"].tolist()
            encoded = (json.dumps(values, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            self.assertEqual(measured["source"]["sha256"], hashlib.sha256(encoded).hexdigest())
            self.assertTrue(measured["source"]["basename"].startswith("synthetic-"))
            self.assertNotIn("/", measured["source"]["basename"])

    def test_actual_contract_joins_are_reproducible(self):
        self.assertEqual(analyze(self.data["measurements"], self.data["manifest"]), self.data["experiment"])
        self.assertEqual(link_experiment(self.data["experiment"], self.data["sort_bins"], self.data["variant_counts"]), self.data["linked"])
        self.assertEqual(self.data["experiment"]["summary"]["known_batch_count"], 1)
        self.assertEqual(self.data["experiment"]["comparison_status"], "exploratory_only")

    def test_sort_counts_are_separate_and_join_shift_b_first_replicate(self):
        bins = self.data["sort_bins"]["bins"]
        self.assertEqual(len(bins), 4)
        self.assertTrue(all(row["sample_id"] == "synthetic-shift-b-r1" for row in bins))
        self.assertEqual(len(self.data["variant_counts"]["counts"]), 32)
        self.assertEqual(len(self.data["linked"]["observed_variant_ids"]), 8)
        self.assertTrue(self.data["metadata"]["sort_count_model"]["independent_of_event_cloud"])
        self.assertEqual(self.data["linked"]["analysis_status"], "descriptive_linkage_only")
        for index, bin_record in enumerate(self.data["linked"]["bins"]):
            rows = [row for row in self.data["linked"]["linked_counts"] if row["bin_id"] == bin_record["bin_id"]]
            self.assertEqual(sum(row["read_count"] for row in rows), self.data["metadata"]["sort_count_model"]["read_depths"][index])
            self.assertAlmostEqual(sum(row["read_fraction_within_sequencing_sample"] for row in rows), 1)
            self.assertTrue(all(type(row["read_count"]) is int for row in rows))

    def test_same_seed_determinism_and_changed_seed(self):
        first = gallery.build_dataset(seed=19, events_per_sample=120)
        same = gallery.build_dataset(seed=19, events_per_sample=120)
        other = gallery.build_dataset(seed=20, events_per_sample=120)
        self.assertEqual(first["metadata"], same["metadata"])
        self.assertEqual(first["measurements"], same["measurements"])
        self.assertEqual(first["variant_counts"], same["variant_counts"])
        for a, b in zip(first["samples"], same["samples"]):
            self.np.testing.assert_array_equal(a["events"], b["events"])
        self.assertFalse(self.np.array_equal(first["samples"][0]["events"], other["samples"][0]["events"]))
        self.assertNotEqual(first["measurements"]["samples"][0]["source"]["sha256"], other["measurements"]["samples"][0]["source"]["sha256"])

    def test_outputs_do_not_mutate_other_calls_and_json_contracts_are_finite(self):
        before = deepcopy(self.data["measurements"])
        separate = gallery.build_dataset(events_per_sample=100)
        separate["measurements"]["samples"][0]["sample_id"] = "edited-test-copy"
        self.assertEqual(self.data["measurements"], before)
        for key in ("metadata", "measurements", "manifest", "experiment", "sort_bins", "variant_counts", "linked"):
            json.dumps(self.data[key], allow_nan=False)


if __name__ == "__main__":
    unittest.main()
