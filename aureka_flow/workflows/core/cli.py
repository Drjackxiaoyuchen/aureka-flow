"""Small explicit CLI. Original inputs are never written."""

import argparse
import json
from pathlib import Path
import sys

from .core import analyze_fcs, demo, inspect_fcs


def _reject_constant(value):
    raise ValueError(f"JSON: nonfinite literal {value} is forbidden")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON: duplicate key {key}")
        result[key] = value
    return result


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_constant, object_pairs_hook=_unique_pairs)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Yeast FACS measurement software alpha; not biological validation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "analyze", "demo"):
        cmd = sub.add_parser(name)
        if name != "demo":
            cmd.add_argument("fcs", type=Path)
        if name == "analyze":
            cmd.add_argument("--config", type=Path, required=True)
            cmd.add_argument("--qc-mask", type=Path, help="Explicit external original-event mask JSON; never inferred")
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        for field in ("fcs", "config", "qc_mask"):
            source = getattr(args, field, None)
            if source is not None and (args.output.resolve() == source.resolve() or
                (args.output.exists() and source.exists() and args.output.samefile(source))):
                raise ValueError(f"output: must not replace the input {field}")
        if args.output.is_symlink():
            raise ValueError("output: symbolic links are not allowed")
        if args.output.exists() and not args.overwrite:
            raise ValueError("output: already exists; use --overwrite explicitly")
        if args.command == "inspect":
            result = inspect_fcs(args.fcs)
        elif args.command == "analyze":
            result = analyze_fcs(args.fcs, load_json(args.config), qc_mask=load_json(args.qc_mask) if args.qc_mask else None)
        else:
            result = demo()
        encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
        with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as handle:
            handle.write(encoded)
        print(f"Wrote {args.output.name}")
        return 0
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
