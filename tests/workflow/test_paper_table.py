"""Checks for a licensed published summary, not a reanalysis of raw measurements."""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "examples" / "workflows" / "papers" / "data" / "adams-2016-table1.json"
spec = importlib.util.spec_from_file_location("extract_adams_table", ROOT / "examples" / "workflows" / "papers" / "extract_adams_table.py")
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


def article_fixture():
    """Minimal synthetic HTML, with no actual author code or sequence data."""
    cells = ["Name", "1H variable region", "3H <br/>variable region", "No. replicates (flow)",
             "<math><msub><mi>K</mi><mi>D</mi></msub></math> [M] (flow)",
             "<math><msub><mi>K</mi><mi>D</mi></msub></math> [M] (Tite-Seq)"]
    header = "<thead><tr>" + "".join(f"<th>{cell}</th>" for cell in cells) + "</tr></thead>"
    rows = []
    for clone in extractor.CLONES:
        count = {"WT": 10, "Δ": 12}.get(clone, 3)
        values = [clone, "omitted", "omitted", str(count), "10<sup>−7.0±0.20</sup>", "10<sup>−7.1±0.30</sup>"]
        rows.append("<tr>" + "".join(f'<td><span class="monospace">{value}</span></td>' for value in values) + "</tr>")
    table_html = "<table>" + header + "<tbody>" + "".join(rows) + "</tbody></table>"
    return {"id": "23156", "doi": extractor.PAPER_DOI,
            "title": "Measuring the sequence-affinity landscape of antibodies with massively parallel titration curves",
            "copyright": {"license": "CC-BY-4.0", "holder": "Adams et al."},
            "authors": [{"name": {"preferred": author}} for author in extractor.AUTHORS],
            "body": [{"content": [{"type": "table", "id": "tbl1", "doi": extractor.TABLE_DOI,
                                   "caption": [{"text": "three replicate Tite-Seq experiments; not averaged across synonymous variants"}],
                                   "tables": [table_html]}]}]}


def table_of(article):
    return article["body"][0]["content"][0]


class PublishedTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        cls.by_clone = {row["clone"]: row for row in cls.data["rows"]}

    def test_attribution_and_provenance(self):
        extractor.validate_data(self.data)
        self.assertEqual(self.data["evidence_kind"], "published_summary")
        self.assertEqual(self.data["paper"]["doi"], "10.7554/eLife.23156")
        self.assertEqual(self.data["source"]["table_doi"], "10.7554/eLife.23156.018")
        self.assertEqual(self.data["paper"]["license"], "CC-BY-4.0")
        self.assertEqual(self.data["paper"]["copyright_holder"], "Adams et al.")
        self.assertEqual(self.data["source"]["sha256"], "f9d439ef1b0bbc9134baa3612a19127b3982ad3af104a9b6a3864bac5c064c97")
        self.assertEqual(self.data["source"]["table_html_sha256"], "ac6680e598ae101348333be216182a2afaf8f1e6a4731f41d94f8efeb93cc254")
        self.assertEqual(self.data["source"]["retrieved_date"], "2026-10-01")
        serialized = json.dumps(self.data, allow_nan=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("/Volumes/", serialized)
        self.assertNotIn("sequence", " ".join(self.by_clone["WT"]))

    def test_original_order_and_replicate_denominators(self):
        expected = ["OPT", "C107", "C112", "WT", "C144", "C133", "C132", "C94", "C5", "C93",
                    "C39", "C102", "C22", "C7", "C45", "C103", "C3", "C18", "Δ"]
        self.assertEqual([row["clone"] for row in self.data["rows"]], expected)
        self.assertEqual(len(self.data["rows"]), 19)
        self.assertEqual(self.by_clone["WT"]["flow_replicates"], 10)
        self.assertEqual(self.by_clone["Δ"]["flow_replicates"], 12)
        self.assertTrue(all(row["flow_replicates"] == 3 for row in self.data["rows"] if row["clone"] not in {"WT", "Δ"}))
        self.assertTrue(all(row["titeseq_replicates"] == 3 for row in self.data["rows"]))
        self.assertIn("not synonymous-variant averaging", self.data["columns"]["titeseq_replicates"])

    def test_exact_wt_means_and_log_space_sem(self):
        wt = self.by_clone["WT"]
        self.assertEqual((wt["flow"]["log10_kd_m"], wt["flow"]["sem_log10"]), (-8.61, 0.07))
        self.assertEqual((wt["titeseq"]["log10_kd_m"], wt["titeseq"]["sem_log10"]), (-8.92, 0.10))
        self.assertEqual(wt["titeseq"]["source_expression"], "10<sup>−8.92±0.10</sup>")
        self.assertIn("not a standard deviation", self.data["columns"]["sem_log10"])

    def test_discordant_clones_are_not_filtered_out(self):
        c22, c102 = self.by_clone["C22"], self.by_clone["C102"]
        self.assertEqual((c22["flow"]["log10_kd_m"], c22["flow"]["sem_log10"]), (-5.69, 0.31))
        self.assertEqual((c22["titeseq"]["log10_kd_m"], c22["titeseq"]["sem_log10"]), (-7.53, 0.07))
        self.assertEqual((c102["flow"]["log10_kd_m"], c102["flow"]["sem_log10"]), (-5.76, 0.16))
        self.assertEqual((c102["titeseq"]["log10_kd_m"], c102["titeseq"]["sem_log10"]), (-7.25, 0.60))

    def test_fourteen_uncensored_pairs_and_five_bound_clones(self):
        exact = [row for row in self.data["rows"] if all(row[method]["qualifier"] == "estimate" for method in ("flow", "titeseq"))]
        bounded = [row["clone"] for row in self.data["rows"] if row not in exact]
        self.assertEqual(len(exact), 14)
        self.assertEqual(bounded, ["OPT", "C45", "C3", "C18", "Δ"])
        for row in self.data["rows"]:
            for method in ("flow", "titeseq"):
                value = row[method]
                if value["qualifier"] == "estimate":
                    self.assertGreater(value["sem_log10"], 0)
                else:
                    self.assertIsNone(value["sem_log10"])
                    self.assertTrue(value["qualifier"].startswith("approximately_"))
        self.assertEqual(self.by_clone["OPT"]["flow"]["source_expression"], "≲10<sup>−9.5</sup>")
        self.assertEqual(self.by_clone["C45"]["flow"]["qualifier"], "estimate")
        self.assertEqual(self.by_clone["C45"]["titeseq"]["qualifier"], "approximately_at_or_above")

    def test_every_retained_expression_independently_matches_numbers(self):
        for row in self.data["rows"]:
            for method in ("flow", "titeseq"):
                value = row[method]
                self.assertEqual(extractor.parse_affinity(value["source_expression"]), value)

    def test_reject_changed_provenance_schema_and_semantics(self):
        mutations = [lambda d: d.update(schema="unknown"),
                     lambda d: d.update(evidence_kind="raw_events"),
                     lambda d: d["paper"].update(license="MIT"),
                     lambda d: d["paper"].update(authors=["Wrong author"]),
                     lambda d: d["source"].update(sha256="abc"),
                     lambda d: d["source"].update(table_html_sha256="A" * 64),
                     lambda d: d["source"].update(api_url="https://example.org"),
                     lambda d: d["source"].update(table_doi="10.7554/eLife.23156.019"),
                     lambda d: d["source"].update(retrieved_date="2026-02-30"),
                     lambda d: d["columns"].update(sem_log10="standard deviation"),
                     lambda d: d["rows"].pop(),
                     lambda d: d["rows"].reverse(),
                     lambda d: d["rows"][3].update(flow_replicates=3),
                     lambda d: d["rows"][0].update(titeseq_replicates=True),
                     lambda d: d["rows"][0].update(sequence="not requested")]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = deepcopy(self.data)
                mutate(data)
                with self.assertRaises(ValueError):
                    extractor.validate_data(data)

    def test_reject_changed_values_nonfinite_and_exact_bounds(self):
        for patch in ({"log10_kd_m": -7.0}, {"log10_kd_m": float("nan")}, {"sem_log10": float("inf")},
                      {"sem_log10": True}, {"sem_log10": -0.1}, {"qualifier": "at_or_below"},
                      {"source_expression": "≤10<sup>−9.5</sup>"}):
            with self.subTest(patch=patch):
                data = deepcopy(self.data)
                data["rows"][0]["flow"].update(patch)
                with self.assertRaises(ValueError):
                    extractor.validate_data(data)


class PublisherExtractorTests(unittest.TestCase):
    def test_parse_minimal_html_without_executing_author_code(self):
        article = article_fixture()
        data = extractor.parse_article(article, "a" * 64)
        self.assertEqual(len(data["rows"]), 19)
        self.assertEqual(data["rows"][0]["flow"]["log10_kd_m"], -7.0)
        self.assertEqual(data["rows"][0]["flow"]["source_expression"], "10<sup>−7.0±0.20</sup>")
        table_hash = hashlib.sha256(table_of(article)["tables"][0].encode("utf-8")).hexdigest()
        self.assertEqual(data["source"]["table_html_sha256"], table_hash)

    def test_entities_keep_raw_source_and_decode_numbers(self):
        raw = "&#8818;10<sup>&#8722;9.5</sup>"
        value = extractor.parse_affinity(raw)
        self.assertEqual(value["source_expression"], raw)
        self.assertEqual(value["qualifier"], "approximately_at_or_below")
        self.assertEqual(value["log10_kd_m"], -9.5)
        article = article_fixture()
        table = table_of(article)
        table["tables"][0] = table["tables"][0].replace("10<sup>−7.0±0.20</sup>", raw, 1)
        self.assertEqual(extractor.parse_article(article, "b" * 64)["rows"][0]["flow"], value)

    def test_reject_affinity_ambiguity_or_missing_sem(self):
        invalid = ["10−7.0±0.2", "10<sup>−7.0</sup>", "≲10<sup>−9.5±0.1</sup>",
                   "≲10<sup>−8.0</sup>", "≳10<sup>−4.0</sup>", "≤10<sup>−9.5</sup>",
                   "10<sup>−7.0±−0.2</sup>", "10<sup>NaN±0.2</sup>", None, 2]
        for expression in invalid:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                extractor.parse_affinity(expression)

    def test_reject_wrong_article_license_table_and_caption(self):
        mutations = [lambda a: a.update(doi="wrong"), lambda a: a.update(id="999"),
                     lambda a: a["copyright"].update(license="all rights reserved"),
                     lambda a: a["authors"].pop(), lambda a: table_of(a).update(doi="wrong"),
                     lambda a: table_of(a).update(caption=[]),
                     lambda a: table_of(a)["tables"].append("duplicate"),
                     lambda a: a["body"].append(deepcopy(a["body"][0]))]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                article = article_fixture()
                mutate(article)
                with self.assertRaises(ValueError):
                    extractor.parse_article(article, "c" * 64)

    def test_reject_changed_headers_row_shape_and_malformed_html(self):
        valid = table_of(article_fixture())["tables"][0]
        invalid = [valid.replace("<th>Name</th>", "<th>Other</th>"),
                   valid.replace("<th>Name</th>", ""), valid.replace("</tbody>", ""),
                   valid.replace("<sup>", '<sup onclick="bad">', 1),
                   valid.replace("<td>", "<td><td>", 1),
                   valid.replace("</table>", "<script>bad</script></table>"),
                   valid.replace("</tbody>", "<tr><td>extra</td></tr></tbody>")]
        for index, html in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                extractor.parse_table_html(html)

    def test_cli_hashes_actual_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            source, output = folder / "publisher.json", folder / "curated.json"
            raw = (json.dumps(article_fixture(), ensure_ascii=False) + "\n").encode("utf-8")
            source.write_bytes(raw)
            with redirect_stdout(io.StringIO()):
                extractor.main(["--input", str(source), "--output", str(output)])
            output_bytes = output.read_bytes()
            result = json.loads(output_bytes)
            self.assertEqual(result["source"]["sha256"], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError, "new file"):
                extractor.main(["--input", str(source), "--output", str(output)])
            self.assertEqual(output.read_bytes(), output_bytes)

    def test_cli_refuses_dangling_symlink_and_symlink_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            source = folder / "publisher.json"
            source.write_text(json.dumps(article_fixture()), encoding="utf-8")
            link = folder / "link.json"
            link.symlink_to(folder / "missing.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                extractor.main(["--input", str(source), "--output", str(link)])
            actual = folder / "actual"
            actual.mkdir()
            parent_link = folder / "parent-link"
            parent_link.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                extractor.main(["--input", str(source), "--output", str(parent_link / "new.json")])
            self.assertFalse((actual / "new.json").exists())


if __name__ == "__main__":
    unittest.main()
