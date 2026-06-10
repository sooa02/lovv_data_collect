"""Lambda handler to preprocess one KR raw JSON object and load domain items."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from kr_details_pipeline import load, transform
from kr_details_pipeline.domain_preprocess import preprocess_city_payload


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    import boto3

    bucket, raw_key = _extract_s3_target(event)
    table_name = str(event.get("table_name") or os.getenv("DYNAMODB_TABLE") or "TourKoreaDomainData")
    processed_prefix = str(event.get("processed_prefix") or os.getenv("PROCESSED_PREFIX") or "processed/KR/domain")
    write_processed = bool(event.get("write_processed", True))

    s3 = boto3.client("s3")
    ddb = boto3.client("dynamodb")

    raw_body = s3.get_object(Bucket=bucket, Key=raw_key)["Body"].read().decode("utf-8")
    payload = json.loads(raw_body)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from s3://{bucket}/{raw_key}")

    result = preprocess_city_payload(payload, source_key=raw_key, table_name=table_name)
    loaded = 0
    failed = 0
    failures: list[dict[str, str]] = []

    for item in result["load_items"]:
        try:
            ddb_item = dict(item)
            ddb_item.pop("table", None)
            load._write_item(ddb, table_name, ddb_item)
            loaded += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failures.append(
                {
                    "entity_id": str(item.get("entity_id") or ""),
                    "content_id": str(item.get("content_id") or ""),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    summary = {
        **result["summary"],
        "status": "ok" if failed == 0 else "partial",
        "bucket": bucket,
        "raw_key": raw_key,
        "loaded": loaded,
        "load_failed": failed,
        "executed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if write_processed:
        _write_processed_summary(
            s3=s3,
            bucket=bucket,
            processed_prefix=processed_prefix,
            raw_key=raw_key,
            summary=summary,
            failures=failures,
        )

    return {
        "statusCode": 200 if failed == 0 else 207,
        "summary": summary,
        "failures": failures[:20],
    }


def _extract_s3_target(event: dict[str, Any]) -> tuple[str, str]:
    records = event.get("Records")
    if isinstance(records, list) and records:
        first = records[0]
        if isinstance(first, dict) and isinstance(first.get("s3"), dict):
            bucket = first["s3"]["bucket"]["name"]
            key = first["s3"]["object"]["key"]
            return str(bucket), str(key)

    bucket = event.get("bucket")
    raw_key = event.get("raw_key")
    if not bucket or not raw_key:
        raise ValueError("event must include bucket/raw_key or S3 Records.")
    return str(bucket), str(raw_key)


def _write_processed_summary(
    *,
    s3: Any,
    bucket: str,
    processed_prefix: str,
    raw_key: str,
    summary: dict[str, Any],
    failures: list[dict[str, str]],
) -> None:
    ingest_date = raw_key.split("/")[-2] if "/" in raw_key else "unknown"
    city_file = raw_key.split("/")[-1]
    city_name = city_file.rsplit(".", 1)[0]
    key = f"{processed_prefix.rstrip('/')}/{ingest_date}/{city_name}/summary.json"
    body = transform.as_json({"summary": summary, "failures": failures})
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        Metadata={
            "pipeline_stage": "kr-domain-loader",
            "source_key": raw_key,
            "city_name_en": city_name,
        },
    )
