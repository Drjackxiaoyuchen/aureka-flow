import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from aureka_flow.workflows.sortseq import ValidationError, link_experiment
from aureka_flow.workflows.sortseq.cli import load, main, report
from aureka_flow.workflows.sortseq.linkage import synthetic_inputs


def experiment():
    return {"schema_version":"yeast-facs-experiment/v1","evidence_kind":"synthetic",
            "comparison_status":"metadata_limited","warnings":["No biological replicates"],
            "samples":[{"sample_id":"illustration","event_count":100,"selected_count":80,
                        "gate_status":"exploratory","processing":{"compensation":"none"},
                        "channels":{"FITC-A":{"median":2.0,"finite_count":80}},"qc_flags":[],
                        "control_role":"sample"}]}


class LinkageTests(unittest.TestCase):
    def setUp(self):
        self.e=experiment(); self.b,self.c=synthetic_inputs(self.e)

    def test_synthetic_chain_denominators(self):
        r=link_experiment(self.e,self.b,self.c)
        self.assertEqual(r["schema_version"],"yeast-sortseq-linked/v1")
        self.assertEqual(len(r["linked_counts"]),12)
        self.assertEqual(r["upstream_comparison_status"],"metadata_limited")
        for bin_ in r["bins"]:
            rows=[x for x in r["linked_counts"] if x["bin_id"]==bin_["bin_id"]]
            self.assertAlmostEqual(sum(x["read_fraction_within_sequencing_sample"] for x in rows),1)
            self.assertEqual(sum(x["read_count"] for x in rows),bin_["total_reads"])

    def test_duplicate_bin(self):
        self.b["bins"].append(deepcopy(self.b["bins"][0]))
        with self.assertRaisesRegex(ValidationError,"duplicate bin_id"): link_experiment(self.e,self.b,self.c)

    def test_ambiguous_sequencing_sample(self):
        self.b["bins"][1]["sequencing_sample_id"]=self.b["bins"][0]["sequencing_sample_id"]
        with self.assertRaisesRegex(ValidationError,"multiple bins"): link_experiment(self.e,self.b,self.c)

    def test_unknown_fcs_sample(self):
        self.b["bins"][0]["sample_id"]="unknown"
        with self.assertRaisesRegex(ValidationError,"unknown sample_id"): link_experiment(self.e,self.b,self.c)

    def test_unknown_sequencing_sample(self):
        self.c["counts"][0]["sequencing_sample_id"]="unknown"
        with self.assertRaisesRegex(ValidationError,"unknown sequencing_sample_id"): link_experiment(self.e,self.b,self.c)

    def test_duplicate_count(self):
        self.c["counts"].append(deepcopy(self.c["counts"][0]))
        with self.assertRaisesRegex(ValidationError,"duplicate count key"): link_experiment(self.e,self.b,self.c)

    def test_boolean_count_rejected(self):
        self.c["counts"][0]["read_count"]=True
        with self.assertRaisesRegex(ValidationError,"integer"): link_experiment(self.e,self.b,self.c)

    def test_fractional_count_rejected(self):
        self.c["counts"][0]["read_count"]=1.2
        with self.assertRaises(ValidationError): link_experiment(self.e,self.b,self.c)

    def test_negative_count_rejected(self):
        self.c["counts"][0]["read_count"]=-1
        with self.assertRaises(ValidationError): link_experiment(self.e,self.b,self.c)

    def test_nonfinite_anywhere_rejected(self):
        self.e["custom_metadata"]={"value":float("nan")}
        with self.assertRaisesRegex(ValidationError,"non-finite"): link_experiment(self.e,self.b,self.c)

    def test_missing_count_rows_not_zero(self):
        self.c["counts"]=[]
        r=link_experiment(self.e,self.b,self.c)
        self.assertTrue(all(x["total_reads"] is None for x in r["bins"]))
        self.assertTrue(all(x["count_status"]=="missing" for x in r["bins"]))

    def test_explicit_zero_rows_distinct_from_missing(self):
        for c in self.c["counts"]: c["read_count"]=0
        r=link_experiment(self.e,self.b,self.c)
        self.assertTrue(all(x["total_reads"]==0 for x in r["bins"]))
        self.assertTrue(all(x["read_fraction_within_sequencing_sample"] is None for x in r["linked_counts"]))

    def test_zero_sorted_events_warns_not_division_by_zero(self):
        self.b["bins"][0]["sorted_events"]=0
        r=link_experiment(self.e,self.b,self.c)
        self.assertTrue(any("sorted-event count is zero" in x for x in r["warnings"]))

    def test_synthetic_real_mixing_refused(self):
        self.c["evidence_kind"]="user_data"
        with self.assertRaisesRegex(ValidationError,"agree"): link_experiment(self.e,self.b,self.c)

    def test_demo_real_input_refused(self):
        self.e["evidence_kind"]="user_data"
        with self.assertRaisesRegex(ValidationError,"non-synthetic"): synthetic_inputs(self.e)

    def test_empty_bin_map_refused(self):
        self.b["bins"]=[]
        with self.assertRaisesRegex(ValidationError,"empty"): link_experiment(self.e,self.b,self.c)

    def test_wrong_schema_refused(self):
        self.b["schema_version"]="yeast-sort-bins/v2"
        with self.assertRaisesRegex(ValidationError,"schema_version"): link_experiment(self.e,self.b,self.c)

    def test_duplicate_sample_refused(self):
        self.e["samples"].append(deepcopy(self.e["samples"][0]))
        with self.assertRaisesRegex(ValidationError,"duplicate sample_id"): link_experiment(self.e,self.b,self.c)

    def test_selected_count_must_not_exceed_total(self):
        self.e["samples"][0]["selected_count"]=101
        with self.assertRaisesRegex(ValidationError,"exceeds"): link_experiment(self.e,self.b,self.c)

    def test_channel_count_must_not_exceed_selected(self):
        self.e["samples"][0]["channels"]["FITC-A"]["finite_count"]=81
        with self.assertRaisesRegex(ValidationError,"exceeds"): link_experiment(self.e,self.b,self.c)

    def test_zero_finite_count_requires_null_median(self):
        self.e["samples"][0]["channels"]["FITC-A"]["finite_count"]=0
        with self.assertRaisesRegex(ValidationError,"must be null"): link_experiment(self.e,self.b,self.c)

    def test_qc_flags_propagate(self):
        self.e["samples"][0]["qc_flags"]=["time_scale_inconsistent"]
        r=link_experiment(self.e,self.b,self.c)
        self.assertEqual(r["bins"][0]["upstream_qc_flags"],["time_scale_inconsistent"])

    def test_no_mutation(self):
        before=deepcopy((self.e,self.b,self.c)); link_experiment(self.e,self.b,self.c)
        self.assertEqual((self.e,self.b,self.c),before)

    def test_advisory_threshold_validation(self):
        for value in (0,-1,True,1.5):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                link_experiment(self.e,self.b,self.c,value)

    def test_html_escaping(self):
        self.c["counts"][0]["variant_id"]="<script>alert(1)</script>"
        h=report(link_experiment(self.e,self.b,self.c))
        self.assertNotIn("<script>",h); self.assertIn("&lt;script&gt;",h)

    def test_inputs_unique_json_keys_and_nan(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"bad.json"
            for text in ('{"a":1,"a":2}','{"a":NaN}'):
                p.write_text(text)
                with self.assertRaises(ValidationError): load(p)

    def test_cli_end_to_end_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"experiment.json"; p.write_text(json.dumps(self.e)); out=Path(t)/"out"
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["demo","--experiment",str(p),"--output",str(out)]),0)
                first=(out/"linked_counts.json").read_bytes()
                self.assertEqual(main(["demo","--experiment",str(p),"--output",str(out)]),2)
            self.assertEqual(first,(out/"linked_counts.json").read_bytes())
            self.assertTrue((out/"report.html").exists())


if __name__ == "__main__": unittest.main()
