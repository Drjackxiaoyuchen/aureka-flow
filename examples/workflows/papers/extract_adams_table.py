"""Extract the CC-BY-4.0 Table 1 summary, not raw events or newly fitted affinities.

This original, standard-library-only extractor never fetches data or runs author code.
Download the publisher JSON explicitly, then pass its path to --input. The output
retains superscript expressions as inert source strings, not HTML to be rendered.
"""

import argparse
from datetime import date
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re


SCHEMA = "yeast-facs.paper-summary.v1"
PAPER_DOI = "10.7554/eLife.23156"
TABLE_DOI = "10.7554/eLife.23156.018"
API_URL = "https://api.elifesciences.org/articles/23156"
PAPER_URL = "https://elifesciences.org/articles/23156"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
AUTHORS = ["Rhys M Adams", "Thierry Mora", "Aleksandra M Walczak", "Justin B Kinney"]
CLONES = ["OPT", "C107", "C112", "WT", "C144", "C133", "C132", "C94", "C5",
          "C93", "C39", "C102", "C22", "C7", "C45", "C103", "C3", "C18", "Δ"]
HEADERS = ["Name", "1H variable region", "3H variable region", "No. replicates (flow)",
           "KD [M] (flow)", "KD [M] (Tite-Seq)"]
COLUMNS = {
    "clone": "Published clone identifier, in Table 1 order; sequences are omitted.",
    "flow_replicates": "Number of flow-cytometry replicate measurements in Table 1.",
    "titeseq_replicates": "Three replicate Tite-Seq experiments; not synonymous-variant averaging.",
    "log10_kd_m": "Base-10 logarithm of the authors' fitted Kd in molar units; lower is tighter binding.",
    "sem_log10": "Published standard error in log10(Kd/M), not a standard deviation or linear-molar error; null for approximate bounds.",
    "qualifier": "estimate, approximately_at_or_below (≲), or approximately_at_or_above (≳); bounds are not exact endpoint estimates.",
    "source_expression": "Exact affinity expression including superscript markup, with decorative span removed; treat as inert source text.",
}


class _TableParser(HTMLParser):
    """Keep cell boundaries and superscripts instead of flattening exponents."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.rows = []
        self.stack = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag not in {"table", "thead", "tbody", "tr", "th", "td", "span", "sup", "math", "msub", "mi", "br"}:
            raise ValueError(f"Unsupported table HTML tag: {tag}")
        if tag == "br":
            if self.cell is not None:
                self.cell["text"] += " "
                self.cell["expression"] += " "
            return
        if tag == "tr":
            if self.row is not None:
                raise ValueError("Nested table row")
            self.row = []
        if tag in {"td", "th"}:
            if self.row is None or self.cell is not None:
                raise ValueError("Invalid table cell boundary")
            self.cell = {"text": "", "expression": ""}
        if tag == "sup":
            if self.cell is None or attrs:
                raise ValueError("Unsupported superscript structure")
            self.cell["expression"] += self.get_starttag_text()
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag != "br":
            raise ValueError("Unexpected self-closing table element")
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("Unbalanced table HTML")
        if tag == "sup":
            self.cell["expression"] += "</sup>"
        if tag in {"td", "th"}:
            self.row.append(self.cell)
            self.cell = None
        if tag == "tr":
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data
            self.cell["expression"] += data

    def handle_entityref(self, name):
        self._entity(f"&{name};")

    def handle_charref(self, name):
        self._entity(f"&#{name};")

    def _entity(self, value):
        if self.cell is not None:
            self.cell["text"] += unescape(value)
            self.cell["expression"] += value


def parse_table_html(table_html):
    """Return 19 six-cell records, failing on changed headers or malformed markup."""
    if not isinstance(table_html, str):
        raise ValueError("Table HTML must be a string")
    parser = _TableParser()
    parser.feed(table_html)
    parser.close()
    if parser.stack or parser.cell is not None or parser.row is not None:
        raise ValueError("Unclosed table HTML")
    if len(parser.rows) != 20 or any(len(row) != 6 for row in parser.rows):
        raise ValueError("Expected one header and 19 rows with six columns")
    if [" ".join(cell["text"].split()) for cell in parser.rows[0]] != HEADERS:
        raise ValueError("Unexpected Table 1 column headers")
    return parser.rows[1:]


def parse_affinity(expression):
    """Interpret only the publisher's mean±SEM or approximate-bound syntax."""
    if not isinstance(expression, str):
        raise ValueError("Affinity source expression must be a string")
    decoded = unescape(expression)
    match = re.fullmatch(r"([≲≳]?)10<sup>([−-]\d+(?:\.\d+)?)(?:±(\d+(?:\.\d+)?))?</sup>", decoded)
    if match is None:
        raise ValueError("Unsupported affinity source expression")
    sign, mean, sem = match.groups()
    mean = float(mean.replace("−", "-"))
    if sign and sem is not None or not sign and sem is None:
        raise ValueError("Estimate must have SEM; approximate bound must not")
    if sign and mean != {"≲": -9.5, "≳": -5.0}[sign]:
        raise ValueError("Unexpected detection-limit bound")
    return {"log10_kd_m": mean, "sem_log10": float(sem) if sem is not None else None,
            "qualifier": {"": "estimate", "≲": "approximately_at_or_below", "≳": "approximately_at_or_above"}[sign],
            "source_expression": expression}


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def parse_article(article, source_sha256, retrieved_date="2026-10-01"):
    """Extract one licensed publisher summary; source_sha256 hashes original bytes."""
    if not isinstance(article, dict) or article.get("id") != "23156" or article.get("doi") != PAPER_DOI:
        raise ValueError("Expected eLife article 23156 and its exact DOI")
    copyright_record = article.get("copyright", {})
    if copyright_record.get("license") != "CC-BY-4.0" or copyright_record.get("holder") != "Adams et al.":
        raise ValueError("Unexpected copyright/license; review reuse permission")
    authors = [author.get("name", {}).get("preferred") for author in article.get("authors", [])]
    if authors != AUTHORS:
        raise ValueError("Unexpected article authors")
    tables = [item for item in _objects(article) if item.get("id") == "tbl1"]
    if len(tables) != 1 or tables[0].get("doi") != TABLE_DOI or tables[0].get("type") != "table":
        raise ValueError("Expected exactly one Table 1 and its exact DOI")
    table = tables[0]
    if len(table.get("tables", [])) != 1:
        raise ValueError("Expected exactly one Table 1 HTML payload")
    caption = " ".join(item.get("text", "") for item in table.get("caption", []))
    if "three replicate Tite-Seq experiments" not in caption or "not averaged across synonymous variants" not in caption:
        raise ValueError("Table caption lacks expected replicate interpretation")
    table_html = table["tables"][0]
    rows = []
    for cells in parse_table_html(table_html):
        flow_replicates = cells[3]["text"].strip()
        if not flow_replicates.isdecimal():
            raise ValueError("Invalid flow replicate count")
        rows.append({"clone": cells[0]["text"].strip(), "flow_replicates": int(flow_replicates),
                     "titeseq_replicates": 3, "flow": parse_affinity(cells[4]["expression"]),
                     "titeseq": parse_affinity(cells[5]["expression"])})
    data = {"schema": SCHEMA, "evidence_kind": "published_summary",
            "paper": {"title": article.get("title"), "doi": PAPER_DOI, "url": PAPER_URL, "authors": authors,
                      "copyright_holder": copyright_record["holder"], "license": "CC-BY-4.0", "license_url": LICENSE_URL},
            "source": {"api_url": API_URL, "sha256": source_sha256, "retrieved_date": retrieved_date,
                       "table_id": "tbl1", "table_doi": TABLE_DOI,
                       "table_html_sha256": hashlib.sha256(table_html.encode("utf-8")).hexdigest()},
            "columns": dict(COLUMNS), "rows": rows}
    validate_data(data)
    return data


def validate_data(data):
    """Validate provenance, units, row order, replicates and censored measurements."""
    if not isinstance(data, dict) or set(data) != {"schema", "evidence_kind", "paper", "source", "columns", "rows"}:
        raise ValueError("Invalid published-summary schema keys")
    if data["schema"] != SCHEMA or data["evidence_kind"] != "published_summary" or data["columns"] != COLUMNS:
        raise ValueError("Invalid schema, evidence kind or column semantics")
    paper, source = data["paper"], data["source"]
    expected_paper = {"title": "Measuring the sequence-affinity landscape of antibodies with massively parallel titration curves",
                      "doi": PAPER_DOI, "url": PAPER_URL, "authors": AUTHORS, "copyright_holder": "Adams et al.",
                      "license": "CC-BY-4.0", "license_url": LICENSE_URL}
    if paper != expected_paper:
        raise ValueError("Invalid paper attribution or license")
    if not isinstance(source, dict) or set(source) != {"api_url", "sha256", "retrieved_date", "table_id", "table_doi", "table_html_sha256"}:
        raise ValueError("Invalid source provenance keys")
    if source["api_url"] != API_URL or source["table_id"] != "tbl1" or source["table_doi"] != TABLE_DOI:
        raise ValueError("Invalid publisher/table provenance")
    for key in ("sha256", "table_html_sha256"):
        if not isinstance(source[key], str) or re.fullmatch(r"[a-f0-9]{64}", source[key]) is None:
            raise ValueError("Invalid source SHA-256")
    try:
        if date.fromisoformat(source["retrieved_date"]).isoformat() != source["retrieved_date"]:
            raise ValueError("Noncanonical retrieval date")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid source retrieval date") from exc
    rows = data["rows"]
    if not isinstance(rows, list) or len(rows) != 19 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected 19 published rows")
    if [row.get("clone") for row in rows] != CLONES:
        raise ValueError("Invalid clone order or identifiers")
    for row in rows:
        if set(row) != {"clone", "flow_replicates", "titeseq_replicates", "flow", "titeseq"}:
            raise ValueError("Invalid row schema")
        if type(row["flow_replicates"]) is not int or row["flow_replicates"] != {"WT": 10, "Δ": 12}.get(row["clone"], 3):
            raise ValueError("Incorrect flow replicate count")
        if type(row["titeseq_replicates"]) is not int or row["titeseq_replicates"] != 3:
            raise ValueError("Incorrect Tite-Seq replicate count")
        for method in ("flow", "titeseq"):
            value = row[method]
            if not isinstance(value, dict) or set(value) != {"log10_kd_m", "sem_log10", "qualifier", "source_expression"}:
                raise ValueError("Invalid affinity schema")
            for field in ("log10_kd_m", "sem_log10"):
                number = value[field]
                if field == "sem_log10" and number is None:
                    continue
                if type(number) not in (int, float) or not math.isfinite(number):
                    raise ValueError("Affinity and SEM must be finite numbers")
            if value != parse_affinity(value["source_expression"]):
                raise ValueError("Affinity values disagree with source expression")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Explicitly downloaded publisher JSON")
    parser.add_argument("--output", required=True, type=Path, help="New output JSON path; never overwritten")
    parser.add_argument("--retrieved-date", default="2026-10-01")
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink() or any(parent.is_symlink() for parent in args.output.parents):
        raise ValueError("Output must be a new file without symlink parents")
    raw = args.input.read_bytes()
    data = parse_article(json.loads(raw), hashlib.sha256(raw).hexdigest(), args.retrieved_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Extracted {len(data['rows'])} published-summary rows (CC-BY-4.0).")


if __name__ == "__main__":
    main()
