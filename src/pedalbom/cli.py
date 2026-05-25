from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapter import pdf_to_schema_bom
from .mouser import has_mouser_api_key, source_bom
from .schema import load_bom, schema_text, validate_bom, write_json


def main() -> None:
    parser = argparse.ArgumentParser(prog="pedalbom")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_command = subparsers.add_parser(
        "extract", help="Fallback PDF extraction to PedalBOM JSON. Prefer the skill for production use."
    )
    extract_command.add_argument("pdf", type=Path)
    extract_command.add_argument("--out", type=Path, help="Write extracted BOM JSON to this path.")
    extract_command.add_argument("--quiet", action="store_true", help="Suppress progress messages.")

    validate_command = subparsers.add_parser("validate", help="Validate extracted PedalBOM JSON.")
    validate_command.add_argument("bom", type=Path)
    validate_command.add_argument("--quiet", action="store_true", help="Suppress progress messages.")

    inspect_command = subparsers.add_parser("inspect", help="Print a concise BOM summary.")
    inspect_command.add_argument("bom", type=Path)

    schema_command = subparsers.add_parser("schema", help="Print the PedalBOM JSON schema.")

    doctor_command = subparsers.add_parser("doctor", help="Check local CLI setup for PedalBOM sourcing.")
    doctor_command.add_argument("--api-key", help="Mouser Search API key. Defaults to MOUSER_API_KEY.")

    source_command = subparsers.add_parser("source", help="Source parts through the Mouser Search API.")
    source_command.add_argument("bom", type=Path)
    source_command.add_argument("--out", type=Path, required=True)
    source_command.add_argument("--api-key", help="Mouser Search API key. Defaults to MOUSER_API_KEY.")
    source_command.add_argument("--limit", type=int, default=5, help="Candidate count to keep per row.")
    source_command.add_argument(
        "--rate-limit-delay",
        type=float,
        default=2.1,
        help="Seconds to wait between unique Mouser search calls.",
    )
    source_command.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry count for Mouser rate-limit responses.",
    )
    source_command.add_argument(
        "--retry-delay",
        type=float,
        default=60.0,
        help="Seconds to wait before retrying after a Mouser rate-limit response.",
    )
    source_command.add_argument("--quiet", action="store_true", help="Suppress progress messages.")

    export_command = subparsers.add_parser("export", help="Export PedalBOM JSON to CSV.")
    export_command.add_argument("bom", type=Path)
    export_command.add_argument("--out", type=Path, required=True)
    export_command.add_argument("--quiet", action="store_true", help="Suppress progress messages.")

    args = parser.parse_args()
    if args.command == "extract":
        progress(args, f"Extracting draft BOM from {args.pdf}.")
        bom = pdf_to_schema_bom(args.pdf)
        progress(args, "Validating extracted BOM.")
        result = validate_bom(bom)
        if args.out:
            progress(args, f"Writing extracted BOM to {args.out}.")
            write_json(bom, args.out)
        else:
            print(json.dumps(bom, indent=2, ensure_ascii=False))
        print_validation_result(result, stream=sys.stderr)
        if not result.ok:
            raise SystemExit(1)
    elif args.command == "validate":
        progress(args, f"Loading BOM from {args.bom}.")
        result = validate_bom(load_bom(args.bom))
        print_validation_result(result)
        raise SystemExit(0 if result.ok else 1)
    elif args.command == "inspect":
        print_summary(load_bom(args.bom))
    elif args.command == "schema":
        print(schema_text(), end="")
    elif args.command == "doctor":
        print("PedalBOM CLI: OK", flush=True)
        if has_mouser_api_key(args.api_key):
            print("MOUSER_API_KEY: set", flush=True)
        else:
            print("MOUSER_API_KEY: missing", flush=True)
            print("Set MOUSER_API_KEY in the local shell before running `pedalbom source`.", file=sys.stderr)
            raise SystemExit(1)
        print("Mouser sourcing must be run from a network/IP allowed by your Mouser API account.")
    elif args.command == "source":
        progress(args, f"Loading BOM from {args.bom}.")
        bom = load_bom(args.bom)
        progress(args, "Validating BOM before sourcing.")
        result = validate_bom(bom)
        if not result.ok:
            print_validation_result(result, stream=sys.stderr)
            raise SystemExit(1)
        try:
            sourced = source_bom(
                bom,
                api_key=args.api_key,
                limit=args.limit,
                rate_limit_delay=args.rate_limit_delay,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                progress=lambda message: progress(args, message),
            )
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        progress(args, f"Writing sourced BOM to {args.out}.")
        write_json(sourced, args.out)
        print(f"Wrote sourced BOM to {args.out}")
    elif args.command == "export":
        progress(args, f"Loading BOM from {args.bom}.")
        bom = load_bom(args.bom)
        progress(args, "Validating BOM before export.")
        result = validate_bom(bom)
        if not result.ok:
            print_validation_result(result, stream=sys.stderr)
            raise SystemExit(1)
        progress(args, f"Writing CSV to {args.out}.")
        write_schema_csv(bom, args.out)
        print(f"Wrote CSV to {args.out}")


def print_validation_result(result, stream=sys.stdout) -> None:
    for error in result.errors:
        print(f"ERROR: {error}", file=stream)
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=stream)
    if result.ok:
        print("PedalBOM JSON is valid.", file=stream)


def progress(args, message: str) -> None:
    if not getattr(args, "quiet", False):
        print(f"[pedalbom] {message}", file=sys.stderr, flush=True)


def print_summary(bom: dict) -> None:
    counts: dict[str, int] = {}
    for item in bom.get("items", []):
        counts[item.get("category", "unknown")] = counts.get(item.get("category", "unknown"), 0) + 1
    project = bom.get("project", {})
    print(f"Project: {project.get('name', 'Untitled')}")
    if project.get("vendor"):
        print(f"Vendor: {project['vendor']}")
    print(f"Rows: {len(bom.get('items', []))}")
    for category, count in sorted(counts.items()):
        print(f"- {category}: {count}")
    issues = bom.get("issues", [])
    if issues:
        print(f"Issues: {len(issues)}")


def write_schema_csv(bom: dict, path: Path) -> None:
    import csv

    columns = [
        "part_id",
        "value",
        "quantity",
        "category",
        "notes",
        "manufacturer_part_number",
        "mouser_part_number",
        "supplier",
        "product_url",
        "selection_rationale",
        "source_evidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in bom["items"]:
            writer.writerow({column: item.get(column, "") for column in columns})


if __name__ == "__main__":
    main()
