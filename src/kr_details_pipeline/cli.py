"""Command line entrypoint for KR details pipeline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from kr_details_pipeline.domain_preprocess import preprocess_city_file
from kr_details_pipeline.raw_ingest import RawIngestConfig, ingest_raw_details
from kr_details_pipeline.transform import transform_raw_city, build_city_record


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KR details pipeline utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    raw_ingest = subparsers.add_parser("raw-ingest", help="Upload KR details JSON files to S3 Raw.")
    raw_ingest.add_argument("--input-dir", type=Path, default=Path("data/KR/details"))
    raw_ingest.add_argument("--output-dir", type=Path, default=Path("data/KR/ingest"))
    raw_ingest.add_argument("--bucket", required=True)
    raw_ingest.add_argument("--profile", help="AWS profile name, e.g. skn26_final.")
    raw_ingest.add_argument("--region", default="us-east-1")
    raw_ingest.add_argument("--ingest-date", default=datetime.now().strftime("%Y%m%d"))
    raw_ingest.add_argument("--overwrite", action="store_true")

    transform_cmd = subparsers.add_parser("transform", help="Transform raw KR detail JSON files to processed payloads.")
    transform_cmd.add_argument("--raw-dir", type=Path, required=True, help="Directory containing raw KR detail JSON files.")
    transform_cmd.add_argument("--output-dir", type=Path, required=True, help="Output directory for transformed records.")
    transform_cmd.add_argument("--ingest-date", default=datetime.now().strftime("%Y%m%d"))

    load_cmd = subparsers.add_parser("load", help="Build deterministic DDB items from processed payloads.")
    load_cmd.add_argument("--processed-dir", type=Path, required=True, help="Directory containing processed city payload files.")
    load_cmd.add_argument("--table-name", default="TourKoreaData")
    load_cmd.add_argument("--output", type=Path, default=None, help="Optional path to write load candidates as JSONL.")

    domain_preprocess = subparsers.add_parser("domain-preprocess", help="Split one KR raw detail JSON into restaurant, attraction, and festival items.")
    domain_preprocess.add_argument("--raw-file", type=Path, required=True, help="Raw city detail JSON file.")
    domain_preprocess.add_argument("--output-dir", type=Path, required=True, help="Output directory for domain-specific preprocessing artifacts.")
    domain_preprocess.add_argument("--table-name", default="TourKoreaDomainData")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "raw-ingest":
        return _raw_ingest(args)
    if args.command == "transform":
        return _transform(args)
    if args.command == "load":
        return _load(args)
    if args.command == "domain-preprocess":
        return _domain_preprocess(args)
    raise ValueError(f"Unsupported command: {args.command}")


def _raw_ingest(args: argparse.Namespace) -> int:
    import boto3

    session_kwargs = {}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    if args.region:
        session_kwargs["region_name"] = args.region
    session = boto3.Session(**session_kwargs)
    s3_client = session.client("s3")

    results = ingest_raw_details(
        RawIngestConfig(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            bucket=args.bucket,
            ingest_date=args.ingest_date,
            overwrite=args.overwrite,
        ),
        s3_client,
    )
    uploaded = sum(1 for result in results if result.status == "uploaded")
    skipped = sum(1 for result in results if result.status == "skipped")
    failed = sum(1 for result in results if result.status == "failed")
    print(f"[INFO] raw-ingest completed uploaded={uploaded} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def _transform(args: argparse.Namespace) -> int:
    def _status_from_counts(result: Any) -> str:
        if result.failed:
            return "failed"
        if result.review:
            return "review"
        return "passed"

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = {"passed": 0, "review": 0, "failed": 0}
    for raw_file in sorted(args.raw_dir.rglob("*.json")):
        payload = json.loads(raw_file.read_text(encoding="utf-8"))
        result = transform_raw_city(payload, source_key=str(raw_file))
        city_record = build_city_record(payload)
        city_name = city_record.get("city_name_en", "UNKNOWN")
        status = _status_from_counts(result)
        out_dir = output_dir / args.ingest_date / status
        out_dir.mkdir(parents=True, exist_ok=True)
        output = {
            "status": status,
            "city_record": city_record,
            "records": result.passed + result.review + result.failed,
            "source_key": str(raw_file),
        }
        (out_dir / f"{city_name}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        counts["passed"] += len(result.passed)
        counts["review"] += len(result.review)
        counts["failed"] += len(result.failed)
    print(f"[INFO] transform completed passed={counts['passed']} review={counts['review']} failed={counts['failed']}")
    return 0


def _load(args: argparse.Namespace) -> int:
    output_path = args.output
    if output_path is None:
        print("[ERROR] --output is required for load command")
        return 2
    passed = 0
    failed = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_f = output_path.open("w", encoding="utf-8")

    processed_files = sorted(Path(args.processed_dir).rglob("*.json"))
    for path in processed_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = str(payload.get("status") or "")
        record_count = len(payload.get("records", [])) if isinstance(payload.get("records"), list) else 0
        out_f.write(
            json.dumps(
                {
                    "status": status,
                    "source_path": str(path),
                    "city_id": payload.get("city_record", {}).get("city_id"),
                    "record_count": record_count,
                    "table": args.table_name,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        passed += 1
        if not status:
            failed += 1

    if out_f:
        out_f.close()

    print(f"[INFO] load plan completed passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


def _domain_preprocess(args: argparse.Namespace) -> int:
    summary = preprocess_city_file(args.raw_file, args.output_dir, table_name=args.table_name)
    print(
        "[INFO] domain-preprocess completed "
        f"city={summary['city_name_en']} "
        f"restaurants={summary['restaurants']} "
        f"attractions={summary['attractions']} "
        f"festivals={summary['festivals']} "
        f"review={summary['review']} "
        f"failed={summary['failed']} "
        f"load_items={summary['load_items']}"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
