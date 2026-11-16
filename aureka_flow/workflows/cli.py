"""One entry point for the six connected modules."""
import argparse
import json
import sys

from aureka_flow.workflows.core.cli import main as core_main
from aureka_flow.workflows.workbench.cli import main as workbench_main
from aureka_flow.workflows.sortseq.cli import main as sortseq_main
from .pipeline import MODULES, demo_run, run_batch


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"core","workbench","sortseq"}:
        return {"core":core_main,"workbench":workbench_main,"sortseq":sortseq_main}[argv[0]](argv[1:])
    parser=argparse.ArgumentParser(description="Six-module yeast FACS workflow; software alpha, no automatic biological claims")
    subs=parser.add_subparsers(dest="command",required=True)
    demo=subs.add_parser("demo",help="run the complete synthetic-only workflow")
    demo.add_argument("--output",required=True)
    run=subs.add_parser("run",help="process an explicit batch run manifest; optional FlowKit required")
    run.add_argument("--manifest",required=True); run.add_argument("--output",required=True)
    subs.add_parser("modules",help="list six module responsibilities")
    for name in ("core","workbench","sortseq"):
        subs.add_parser(name,help="forward to component CLI (use this command with --help)")
    args=parser.parse_args(argv)
    try:
        if args.command=="modules":
            print(json.dumps([{"id":m,"name":n,"scope":s} for m,n,s in MODULES],indent=2)); return 0
        result=demo_run(args.output) if args.command=="demo" else run_batch(args.manifest,args.output)
        print(json.dumps({"output":args.output,"evidence_kind":result["evidence_kind"],"comparison_status":result["comparison_status"]}))
        return 0
    except (ValueError,OSError,TypeError,KeyError,RuntimeError,RecursionError) as exc:
        print(f"error: {exc}",file=sys.stderr); return 2
