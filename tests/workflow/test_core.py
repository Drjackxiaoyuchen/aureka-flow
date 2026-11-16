"""Only synthetic fixtures. Native FlowKit cases skip if optional dependency is absent."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from aureka_flow.workflows.core.core import (CONFIG_SCHEMA, _parse_text, analyze_fcs, demo,
                                  inspect_fcs, summarize_events, time_qc, validate_config, validate_qc_mask)
from aureka_flow.workflows.core.cli import load_json, main


def config():
    return {"schema_version": CONFIG_SCHEMA, "sample_id": "synthetic-example", "evidence_kind": "synthetic",
            "channels": ["FITC-A", "APC-A"], "compensation": {"state": "uncompensated", "reason": "Synthetic test"}}


def rectangle():
    return {"gate_id": "test-reference", "scope": "exploratory", "reference_status": "Synthetic cutoff, not biology",
            "bounds": {"FITC-A": {"min": 0, "max": 10}}}


def summary(events, cfg=None, **kwargs):
    return summarize_events(events, ["FITC-A", "APC-A", "Time"], cfg or config(),
                            source={"basename": "synthetic.fcs", "sha256": "0" * 64}, **kwargs)["samples"][0]


def header_only_file(path, extra=None):
    meta = {"$TOT": "4", "$PAR": "3", "$P1N": "FITC-A", "$P2N": "APC-A", "$P3N": "Time", "$DATATYPE": "F", "$MODE": "L"}
    meta.update(extra or {})
    text = ("|" + "|".join(value.replace("|", "||") for pair in meta.items() for value in pair) + "|").encode("latin-1")
    header = b"FCS3.1    " + f"{58:8d}{57+len(text):8d}{0:8d}{0:8d}{0:8d}{0:8d}".encode()
    path.write_bytes(header + text)


class ConfigTests(unittest.TestCase):
    def test_valid_ungated(self):
        self.assertEqual(validate_config(config()), config())

    def test_malformed_settings(self):
        for key, value in (("sample_id", ""), ("channels", []), ("channels", ["a", "a"]),
                           ("channels", [False]), ("evidence_kind", "validated"),
                           ("schema_version", "wrong"), ("rectangle_gates", []), ("unknown", 1)):
            with self.subTest(key=key, value=value):
                cfg = config()
                cfg[key] = value
                with self.assertRaises(ValueError):
                    validate_config(cfg)

    def test_compensation_required_and_reasoned(self):
        for comp in (None, {}, {"state": "auto", "reason": "guess"}, {"state": "embedded", "reason": ""}):
            cfg = config()
            cfg["compensation"] = comp
            with self.assertRaises(ValueError):
                validate_config(cfg)
        cfg = config()
        del cfg["compensation"]
        with self.assertRaises(ValueError):
            validate_config(cfg)

    def test_bad_boundaries(self):
        for low, high in ((None, None), (1, 1), (2, 1), (float("nan"), 2), (0, float("inf")), (True, 10)):
            with self.subTest(low=low, high=high):
                cfg = config()
                gate = rectangle()
                gate["bounds"]["FITC-A"] = {"min": low, "max": high}
                cfg["rectangle_gates"] = [gate]
                with self.assertRaises(ValueError):
                    validate_config(cfg)

    def test_empty_missing_and_nonfluorescent_gates(self):
        for bounds in ({}, {"missing": {"min": 0, "max": 2}}, {"Time": {"min": 0, "max": 2}}):
            cfg = config()
            cfg["channels"].append("Time")
            gate = rectangle()
            gate["bounds"] = bounds
            cfg["rectangle_gates"] = [gate]
            with self.assertRaises(ValueError):
                validate_config(cfg)

    def test_duplicate_gate_ids(self):
        cfg = config()
        cfg["rectangle_gates"] = [rectangle(), rectangle()]
        with self.assertRaises(ValueError):
            validate_config(cfg)


class SummaryTests(unittest.TestCase):
    def test_external_mask_intersection_preserves_original_identity(self):
        cfg = config()
        cfg["rectangle_gates"] = [rectangle()]
        mask = {"schema_version": "yeast-facs-qc-mask/v1", "source_sha256": "0" * 64, "event_count": 4,
                "kept_original_event_indices": [3, 0, 2], "method": "Synthetic external mask"}
        sample = summary([[-1, 2, 0], [2, 4, 1], [4, 6, 2], [6, 8, 3]], cfg, qc_mask=mask)
        self.assertEqual(sample["selected_count"], 2)
        self.assertEqual(sample["processing"]["selected_event_ranges"], [[2, 4]])
        self.assertEqual(sample["processing"]["stage_counts"], {"input": 4, "after_external_qc_mask": 3, "after_supplied_rectangles": 2})
        self.assertIn("external_qc_mask_user_supplied_not_independently_validated", sample["qc_flags"])

    def test_invalid_external_mask_binding_and_indices(self):
        base = {"schema_version": "yeast-facs-qc-mask/v1", "source_sha256": "0" * 64, "event_count": 2,
                "kept_original_event_indices": [0, 1], "method": "Synthetic external mask"}
        for key, value in (("source_sha256", "1" * 64), ("event_count", True), ("event_count", 3),
                           ("kept_original_event_indices", [0, 0]), ("kept_original_event_indices", [True]),
                           ("kept_original_event_indices", [-1]), ("kept_original_event_indices", [2]),
                           ("kept_original_event_indices", [0.5]), ("method", "")):
            with self.subTest(key=key, value=value):
                mask = dict(base)
                mask[key] = value
                with self.assertRaises(ValueError):
                    validate_qc_mask(mask, source_sha256="0" * 64, event_count=2)

    def test_empty_external_mask_is_explicit(self):
        mask = {"schema_version": "yeast-facs-qc-mask/v1", "source_sha256": "0" * 64, "event_count": 1,
                "kept_original_event_indices": [], "method": "Synthetic external mask"}
        sample = summary([[1, 2, 0]], qc_mask=mask)
        self.assertEqual(sample["selected_count"], 0)
        self.assertIn("no_selected_events", sample["qc_flags"])

    def test_large_finite_median_remains_finite(self):
        sample = summary([[1e308, 2, 0], [1e308, 3, 1]])
        self.assertEqual(sample["channels"]["FITC-A"]["median"], 1e308)
        json.dumps(sample, allow_nan=False)

    def test_subnormal_median_is_preserved(self):
        self.assertEqual(summary([[5e-324, 2, 0], [5e-324, 3, 1]])["channels"]["FITC-A"]["median"], 5e-324)

    def test_negative_preserved_and_ungated_counts(self):
        sample = summary([[-4, 8, 0], [-2, 12, 1]])
        self.assertEqual(sample["channels"]["FITC-A"]["median"], -3)
        self.assertEqual(sample["channels"]["FITC-A"]["negative_count"], 2)
        self.assertEqual(sample["selected_count"], 2)
        self.assertEqual(sample["gate_status"], "ungated")
        self.assertEqual(sample["processing"]["selected_event_ranges"], [[0, 2]])

    def test_nan_not_silently_imputed(self):
        sample = summary([[float("nan"), 2, 0], [-2, float("inf"), 1]])
        self.assertEqual(sample["selected_count"], 2)
        self.assertEqual(sample["channels"]["FITC-A"]["finite_count"], 1)
        self.assertIn("channel_finite_denominators_differ_from_selected_count", sample["qc_flags"])
        json.dumps(sample, allow_nan=False)

    def test_all_nonfinite_channel_is_null(self):
        sample = summary([[float("nan"), 2, 0]])
        self.assertIsNone(sample["channels"]["FITC-A"]["median"])
        self.assertEqual(sample["channels"]["FITC-A"]["finite_count"], 0)

    def test_supplied_rectangle_end_exclusive_original_indices(self):
        cfg = config()
        cfg["rectangle_gates"] = [rectangle()]
        sample = summary([[-1, 0, 0], [0, 1, 1], [9, 2, 2], [10, 3, 3], [5, 4, 4]], cfg)
        self.assertEqual(sample["selected_count"], 3)
        self.assertEqual(sample["processing"]["selected_event_ranges"], [[1, 3], [4, 5]])
        self.assertEqual(sample["channels"]["APC-A"]["median"], 2)

    def test_nan_gate_value_excluded(self):
        cfg = config()
        cfg["rectangle_gates"] = [rectangle()]
        sample = summary([[float("nan"), 2, 0], [3, 4, 1]], cfg)
        self.assertEqual(sample["selected_count"], 1)
        self.assertEqual(sample["processing"]["selected_event_ranges"], [[1, 2]])

    def test_empty_input_and_empty_selection(self):
        self.assertIn("empty_event_input", summary([])["qc_flags"])
        cfg = config()
        cfg["rectangle_gates"] = [rectangle()]
        sample = summary([[-10, 2, 0]], cfg)
        self.assertEqual(sample["selected_count"], 0)
        self.assertIsNone(sample["channels"]["FITC-A"]["median"])

    def test_gate_intersection(self):
        cfg = config()
        second = rectangle()
        second["gate_id"] = "second"
        second["bounds"] = {"APC-A": {"min": 5, "max": None}}
        second["scope"] = "user_supplied_unvalidated"
        cfg["rectangle_gates"] = [rectangle(), second]
        sample = summary([[5, 2, 0], [5, 8, 1], [15, 8, 2]], cfg)
        self.assertEqual(sample["selected_count"], 1)
        self.assertEqual(sample["gate_status"], "user_supplied_unvalidated")

    def test_no_unperformed_compensation_claim(self):
        cfg = config()
        cfg["compensation"]["state"] = "embedded"
        with self.assertRaisesRegex(ValueError, "not applied"):
            summary([[1, 2, 0]], cfg)

    def test_bad_event_values_and_dimensions(self):
        for events in ([[1, 2]], [[True, 2, 0]], [["1", 2, 0]]):
            with self.assertRaises(ValueError):
                summary(events)

    def test_basename_and_hash_validation(self):
        for source in ({"basename": "/private/synthetic.fcs", "sha256": "0" * 64}, {"basename": "test.fcs", "sha256": "bad"}):
            with self.assertRaises(ValueError):
                summarize_events([], ["FITC-A", "APC-A"], config(), source=source)

    def test_demo_contract_and_provenance(self):
        data = demo()
        self.assertEqual(data["evidence_kind"], "synthetic")
        self.assertEqual(data["schema_version"], "yeast-facs-measurements/v1")
        self.assertEqual(len(data["samples"]), 3)
        for sample in data["samples"]:
            events = sample["processing"]["synthetic_input"]["events"]
            raw = (json.dumps(events, separators=(",", ":")) + "\n").encode()
            self.assertEqual(sample["source"]["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(sample["event_count"], sample["selected_count"])
        json.dumps(data, allow_nan=False)


class TimeTests(unittest.TestCase):
    def test_numeric_overflow_refused(self):
        with self.assertRaisesRegex(ValueError, "finite numeric range"):
            time_qc([-1e308, 1e308], {}, preprocessed=False)

    def test_missing_metadata_not_ready(self):
        flags, _ = time_qc([0, 1], {}, preprocessed=False)
        self.assertIn("time_timestep_missing_or_invalid", flags)
        self.assertIn("time_clock_metadata_missing_or_invalid", flags)

    def test_scaling_exactly_once(self):
        meta = {"btim": "12:00:00", "etim": "12:00:10", "timestep": "0.1"}
        for values, processed in (([0, 100], False), ([0, 10], True)):
            flags, detail = time_qc(values, meta, preprocessed=processed)
            self.assertNotIn("time_scale_clock_mismatch", flags)
            self.assertEqual(detail["time_span_seconds"], 10)

    def test_mismatch_backward_and_nonfinite(self):
        flags, detail = time_qc([0, 1000, 900, float("nan")], {"btim": "12:00:00", "etim": "12:00:10", "timestep": "1"}, preprocessed=False)
        self.assertIn("time_scale_clock_mismatch", flags)
        self.assertIn("time_backward_steps", flags)
        self.assertIn("time_nonfinite_values", flags)
        self.assertEqual(detail["backward_steps"], 1)

    def test_midnight_explicit(self):
        flags, detail = time_qc([0, 2], {"btim": "23:59:59", "etim": "00:00:01", "timestep": "1"}, preprocessed=False)
        self.assertIn("time_clock_midnight_wrap_assumed", flags)
        self.assertEqual(detail["clock_span_seconds"], 2)

    def test_invalid_clock_and_timestep(self):
        flags, _ = time_qc([0, 1], {"btim": "25:00:00", "etim": "12:00:10", "timestep": "NaN"}, preprocessed=False)
        self.assertIn("time_clock_metadata_missing_or_invalid", flags)
        self.assertIn("time_timestep_missing_or_invalid", flags)


class HeaderAndCLITests(unittest.TestCase):
    def test_header_inspect_hash_no_private_full_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.fcs"
            header_only_file(path, {"$FIL": "/do/not/export/source.fcs", "$P1S": "not exported"})
            before = path.read_bytes()
            result = inspect_fcs(path)
            self.assertEqual(result["event_count_declared"], 4)
            self.assertNotIn("/do/not/export", json.dumps(result))
            self.assertNotIn("not exported", json.dumps(result))
            self.assertEqual(result["source"]["sha256"], hashlib.sha256(before).hexdigest())
            self.assertEqual(path.read_bytes(), before)

    def test_text_escaped_delimiter_and_duplicates(self):
        self.assertEqual(_parse_text(b"|$KEY|a||b|"), {"key": "a|b"})
        for data in (b"|$KEY|a|$KEY|b|", b"|$KEY|", b"not-text"):
            with self.assertRaises(ValueError):
                _parse_text(data)

    def test_text_ascii_padding_after_final_delimiter(self):
        self.assertEqual(_parse_text(b"/$KEY/value/" + b" " * 1848), {"key": "value"})

    def test_text_padding_does_not_strip_value_spaces_or_escapes(self):
        self.assertEqual(_parse_text(b"|$KEY| value || more |   "), {"key": " value | more "})

    def test_text_padding_rejects_nonspace_tail_and_duplicate_keys(self):
        for data in (b"|$KEY|a|\t ", b"|$KEY|a|\x00 ", b"|$KEY|a|junk ", b"|$KEY|a|$KEY|b|   "):
            with self.subTest(data=data), self.assertRaises(ValueError):
                _parse_text(data)

    def test_space_delimiter_is_not_stripped_as_padding(self):
        self.assertEqual(_parse_text(b" $KEY value "), {"key": "value"})

    def test_invalid_header_and_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.fcs"
            for content in (b"bad", b"FCS3.1    " + b"       0" * 6, b"FCS3.1    " + b"99999999" * 6):
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    inspect_fcs(path)

    def test_bad_metadata_counts_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.fcs"
            for extra in ({"$TOT": "1.2"}, {"$PAR": "0"}, {"$P2N": "FITC-A"}):
                header_only_file(path, extra)
                with self.assertRaises(ValueError):
                    inspect_fcs(path)

    def test_cli_never_overwrites_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.json"
            self.assertEqual(main(["demo", "--output", str(path)]), 0)
            before = path.read_bytes()
            self.assertEqual(main(["demo", "--output", str(path)]), 2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(main(["demo", "--output", str(path), "--overwrite"]), 0)

    def test_cli_never_replaces_fcs_even_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.fcs"
            header_only_file(path)
            before = path.read_bytes()
            self.assertEqual(main(["inspect", str(path), "--output", str(path), "--overwrite"]), 2)
            self.assertEqual(path.read_bytes(), before)

    def test_cli_never_replaces_hardlinked_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.fcs"
            output = Path(directory) / "same-inode.json"
            header_only_file(path)
            os.link(path, output)
            before = path.read_bytes()
            self.assertEqual(main(["inspect", str(path), "--output", str(output), "--overwrite"]), 2)
            self.assertEqual(path.read_bytes(), before)

    def test_json_rejects_duplicate_and_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for text in ('{"x": NaN}', '{"x": 1, "x": 2}'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_json(path)


@unittest.skipUnless(importlib.util.find_spec("flowkit") and importlib.util.find_spec("flowio"), "optional FlowKit runtime absent")
class NativeSyntheticTests(unittest.TestCase):
    def create(self, path, *, spill=False):
        import flowio
        meta = {"btim": "12:00:00", "etim": "12:00:03", "timestep": "0.1"}
        if spill:
            meta["spillover"] = spill if isinstance(spill, str) else "2,FITC-A,APC-A,1,0,0,1"
        with path.open("wb") as handle:
            flowio.create_fcs(handle, [-4, 2, 0, -2, 4, 10, 4, 6, 20, 8, 10, 30],
                              ["FITC-A", "APC-A", "Time"], metadata_dict=meta)

    def test_native_ungated_metadata_and_immutability(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.fcs"
            self.create(path)
            before = path.read_bytes()
            sample = analyze_fcs(path, config())["samples"][0]
            self.assertEqual(sample["event_count"], 4)
            self.assertEqual(sample["channels"]["FITC-A"]["median"], 1)
            self.assertEqual(sample["channels"]["FITC-A"]["negative_count"], 2)
            self.assertNotIn("time_scale_clock_mismatch", sample["qc_flags"])
            self.assertEqual(path.read_bytes(), before)

    def test_native_supplied_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.fcs"
            self.create(path)
            cfg = config()
            cfg["rectangle_gates"] = [rectangle()]
            sample = analyze_fcs(path, cfg)["samples"][0]
            self.assertEqual(sample["selected_count"], 2)
            self.assertEqual(sample["processing"]["selected_event_ranges"], [[2, 4]])

    def test_native_embedded_present_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.fcs"
            cfg = config()
            cfg["compensation"]["state"] = "embedded"
            self.create(path, spill=False)
            with self.assertRaisesRegex(ValueError, "absent"):
                analyze_fcs(path, cfg)
            self.create(path, spill=True)
            sample = analyze_fcs(path, cfg)["samples"][0]
            self.assertEqual(sample["channels"]["FITC-A"]["median"], 1)
            self.assertEqual(sample["processing"]["compensation"]["state"], "embedded")

    def test_native_nonidentity_spillover_changes_correct_detector(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.fcs"
            spill = "2,FITC-A,APC-A,1,0.5,0,1"
            self.create(path, spill=spill)
            cfg = config()
            cfg["compensation"]["state"] = "embedded"
            sample = analyze_fcs(path, cfg)["samples"][0]
            self.assertEqual(sample["channels"]["FITC-A"]["median"], 1)
            self.assertEqual(sample["channels"]["APC-A"]["median"], 4.5)
            self.assertEqual(sample["processing"]["embedded_spillover_sha256"], hashlib.sha256(spill.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
