"""Small offline CLI. Imports only previously decoded count tables."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import sys

from .linkage import ValidationError, link_experiment, synthetic_inputs


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load(path):
    def reject_constant(value):
        raise ValidationError(f"non-finite JSON constant: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)


def dump(path, data):
    with Path(path).open("x",encoding="utf-8") as stream:
        json.dump(data,stream,indent=2,allow_nan=False)
        stream.write("\n")


def report(result):
    esc=lambda x: html.escape(str(x))
    rows=[]
    for b in result["bins"]:
        rows.append("<tr>"+"".join("<td>"+esc(b[k] if b[k] is not None else "not supplied")+"</td>" for k in
                    ["bin_id","sample_id","sequencing_sample_id","sorted_events","count_status","total_reads"])+"</tr>")
    cells={(r["variant_id"],r["bin_id"]):r for r in result["linked_counts"]}
    matrix=[]
    for v in result["observed_variant_ids"]:
        cols=["<th scope='row'>"+esc(v)+"</th>"]
        for b in result["bins"]:
            row=cells.get((v,b["bin_id"]))
            frac=row["read_fraction_within_sequencing_sample"] if row else None
            if row is None: content="missing"
            elif frac is None: content=f'{row["read_count"]} reads / undefined fraction'
            else: content=f'{row["read_count"]:,} reads / {100*frac:.1f}%'
            shade=0 if frac is None else .04+.55*frac
            cols.append(f'<td style="background:rgba(34,128,118,{shade:.4f})">{content}</td>')
        matrix.append("<tr>"+"".join(cols)+"</tr>")
    warnings="".join("<li>"+esc(w)+"</li>" for w in result["warnings"])
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'">
<title>Yeast sort-seq bridge</title><style>body{font:16px/1.55 system-ui,sans-serif;color:#21383b;background:#f5f8f7;margin:0}main{max-width:1100px;margin:auto;padding:35px 25px}h1{font-weight:600;letter-spacing:-.025em}h2{margin-top:32px;font-weight:500}.note{border-left:3px solid #218076;padding:12px 18px;background:#e9f2ef}.table{overflow:auto}table{border-collapse:collapse;width:100%;background:white}th,td{padding:12px;text-align:left;border-bottom:1px solid #d7e0df;font-size:14px;overflow-wrap:anywhere}li{margin-bottom:8px}code{overflow-wrap:anywhere}footer{color:#5a6d70;margin-top:35px}</style></head><body><main>
<p>AUREKA FLOW / SORT-SEQ</p><h1>From sort-bin identity to variant counts</h1>
<p class="note">"""+esc(result["evidence_kind"].upper())+""" evidence. Descriptive linkage only—not a binding-affinity result. Read fractions use sequencing reads, not sorted cells, as their denominator.</p>
<h2>Traceable sample links</h2><div class="table"><table><thead><tr><th>Bin</th><th>FCS sample</th><th>Sequencing sample</th><th>Sorted events</th><th>Counts</th><th>Total reads</th></tr></thead><tbody>"""+"".join(rows)+"""</tbody></table></div>
<h2>Read composition within each sequencing sample</h2><div class="table"><table><thead><tr><th>Variant</th>"""+"".join("<th>"+esc(b["bin_id"])+"</th>" for b in result["bins"])+"""</tr></thead><tbody>"""+"".join(matrix)+"""</tbody></table></div>
<p>Each percentage divides that variant’s supplied count by the sum of all supplied variant counts in that sequencing sample. Missing rows are not filled with zero. Unequal bin collection and sampling are not corrected here.</p>
<h2>Evidence limits</h2><ul>"""+warnings+"""</ul><p>Upstream comparison status: <code>"""+esc(result["upstream_comparison_status"])+"""</code>. See <a href="linked_counts.json">linked_counts.json</a> for preserved upstream warnings.</p>
<footer>Research software alpha · no raw-read decoding · no Kd fitting · no private data bundled</footer></main></body></html>"""


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    for name in ("link","demo"):
        p=commands.add_parser(name)
        p.add_argument("--experiment",type=Path,required=True)
        p.add_argument("--output",type=Path,required=True,help="New output directory (must not exist)")
        p.add_argument("--min-reads",type=int,default=10)
        if name=="link":
            p.add_argument("--sort-bins",type=Path,required=True)
            p.add_argument("--counts",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        experiment=load(args.experiment)
        if args.command=="demo":
            bins,counts=synthetic_inputs(experiment)
            paths=[args.experiment]
        else:
            bins,counts=load(args.sort_bins),load(args.counts)
            paths=[args.experiment,args.sort_bins,args.counts]
        result=link_experiment(experiment,bins,counts,args.min_reads)
        result["input_provenance"]=[{"basename":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
        rendered=report(result)
        args.output.mkdir(parents=True,exist_ok=False)
        if args.command=="demo":
            dump(args.output/"synthetic_sort_bins.json",bins)
            dump(args.output/"synthetic_variant_counts.json",counts)
        dump(args.output/"linked_counts.json",result)
        with (args.output/"report.html").open("x",encoding="utf-8") as stream: stream.write(rendered)
        print(json.dumps({"status":"descriptive_linkage_only","bins":len(result["bins"]),
                          "count_rows":len(result["linked_counts"]),"output":str(args.output)}))
        return 0
    except (ValidationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"error: {exc}",file=sys.stderr)
        return 2
