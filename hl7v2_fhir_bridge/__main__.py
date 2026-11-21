"""CLI: python -m hl7v2_fhir_bridge <message.hl7> [--transaction] [--pretty]"""

from __future__ import annotations

import argparse
import json
import sys

from .parser import ParseError, parse_message
from .mapper import convert


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hl7v2-fhir-bridge",
        description="Convert an HL7 v2.x ER7 message (ORU focus) into a FHIR R4 Bundle",
    )
    ap.add_argument("input", help="path to the .hl7 message, or - for stdin")
    ap.add_argument("--transaction", action="store_true",
                    help="emit a transaction Bundle (entry.request POST) instead of a collection")
    ap.add_argument("--pretty", action="store_true", help="indent the JSON output")
    args = ap.parse_args(argv)

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()

    try:
        bundle = convert(parse_message(raw), transaction=args.transaction)
    except (ParseError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    json.dump(bundle, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
