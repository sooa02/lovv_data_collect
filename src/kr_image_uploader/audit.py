"""Reconcile uploaded images against the source JSON to find upload failures.

For each city it compares the set of object names that *should* exist in S3
(computed from the raw JSON, exactly like the uploader does) against the set
that actually exists (listed from S3). The difference is the failures.

Optionally (``--check-urls``) it issues an HTTP request for each missing image
URL to classify the cause (e.g. HTTP 404 = dead source image).

Run from ``src/``:

    python -m kr_image_uploader.audit --dir ..\\data\\raw\\KR\\details\\20260609
    python -m kr_image_uploader.audit --dir ..\\data\\raw\\KR\\details\\20260609 --check-urls
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from . import download
from .extract import ImageTarget, collect_image_targets
from .s3_keys import DEFAULT_PREFIX, build_image_key
from .uploader import _content_type, _ext_from_url

DEFAULT_BUCKET = "lovv-image-dev-925273580929"


def expected_files(payload: dict[str, Any], city: str, prefix: str = DEFAULT_PREFIX) -> dict[str, ImageTarget]:
    """Map ``filename -> ImageTarget`` for every image that should be uploaded."""
    result: dict[str, ImageTarget] = {}
    for target in collect_image_targets(payload):
        key = build_image_key(city, target.name, target.suffix, _ext_from_url(target.url), prefix=prefix)
        result[key.rsplit("/", 1)[-1]] = target
    return result


def find_missing(expected: dict[str, ImageTarget], actual_names: set[str]) -> dict[str, ImageTarget]:
    """Return the subset of ``expected`` whose filename is not in ``actual_names``."""
    return {name: target for name, target in expected.items() if name not in actual_names}


def list_s3_filenames(client: Any, bucket: str, prefix: str, city: str) -> set[str]:
    """List object base filenames under ``prefix/city/`` (handles pagination)."""
    names: set[str] = set()
    token: str | None = None
    full_prefix = f"{prefix}/{city}/"
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": full_prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []):
            names.add(obj["Key"].rsplit("/", 1)[-1])
        if response.get("IsTruncated"):
            token = response.get("NextContinuationToken")
        else:
            break
    return names


def check_url(url: str, timeout: int = 15) -> str:
    """Return the real HTTP status (as str) or an error class name for ``url``.

    Uses a GET request (same as the actual download). VisitKorea blocks HEAD and
    answers 405 to it regardless of whether the file exists, so HEAD is useless
    here; GET reports the true status (e.g. 404 = genuinely missing, 200 =
    exists and the earlier failure was transient -> retryable).
    """
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return str(getattr(response, "status", 200))
    except HTTPError as exc:
        return str(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        return type(exc).__name__


def recover_missing(
    client: Any,
    bucket: str,
    prefix: str,
    city: str,
    missing: dict[str, ImageTarget],
    timeout: int = 30,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Re-download each missing image and upload it if the download succeeds.

    Only the missing objects are touched; existing objects are never modified.
    Returns ``(recovered_filenames, failed)`` where ``failed`` is a list of
    ``(filename, status)`` (status = HTTP code or error class, e.g. "404").
    """
    recovered: list[str] = []
    failed: list[tuple[str, str]] = []
    for fname, target in sorted(missing.items()):
        ext = _ext_from_url(target.url)
        key = build_image_key(city, target.name, target.suffix, ext, prefix=prefix)
        try:
            body = download.fetch_bytes(target.url, timeout=timeout)
        except HTTPError as exc:
            failed.append((fname, str(exc.code)))
            continue
        except (URLError, TimeoutError, OSError) as exc:
            failed.append((fname, type(exc).__name__))
            continue
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=_content_type(ext))
        recovered.append(fname)
    return recovered, failed


def _make_s3_client() -> Any:
    import boto3

    return boto3.client("s3")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit uploaded city images vs source JSON.")
    parser.add_argument("--dir", required=True, help="folder containing {City}.json files")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--check-urls", action="store_true",
                        help="HTTP-check each missing image URL to classify the cause")
    parser.add_argument("--retry-missing", action="store_true",
                        help="re-download and upload only the missing images "
                             "(existing objects untouched; dead 404s are skipped)")
    parser.add_argument("--out", help="write the missing-image list to this CSV path")
    args = parser.parse_args(argv)

    client = _make_s3_client()
    files = sorted(f for f in os.listdir(args.dir) if f.lower().endswith(".json"))

    rows: list[tuple[str, int, int, int, int]] = []  # city, expected, ok, failed, recovered
    failure_rows: list[tuple[str, str, str, str, str, str]] = []  # for --out CSV
    total_expected = total_failed = total_recovered = 0

    for name in files:
        city = os.path.splitext(name)[0]
        with open(os.path.join(args.dir, name), "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        expected = expected_files(payload, city, args.prefix)
        actual = list_s3_filenames(client, args.bucket, args.prefix, city)
        missing = find_missing(expected, actual)

        recovered: list[str] = []
        if args.retry_missing and missing:
            recovered, retry_failed = recover_missing(client, args.bucket, args.prefix, city, missing)
            if recovered or retry_failed:
                print(f"\n[{city}] retry: recovered {len(recovered)} / "
                      f"still failed {len(retry_failed)} (of {len(missing)} missing)")
                for fname in recovered:
                    print(f"    [RECOVERED] {fname}")
                for fname, status in retry_failed:
                    print(f"    [skip {status}] {fname}")
        elif missing:
            print(f"\n[{city}] failed {len(missing)} / {len(expected)}")
            for fname, target in sorted(missing.items()):
                status = check_url(target.url) if (args.check_urls or args.out) else ""
                cause = f"  ->  {status}" if status else ""
                print(f"    {fname}  ({target.title}){cause}")
                print(f"      {target.url}{cause}")
                if args.out:
                    failure_rows.append(
                        (city, target.content_id, target.title, fname, target.url, status)
                    )

        failed_after = len(missing) - len(recovered)
        rows.append((city, len(expected), len(expected) - failed_after, failed_after, len(recovered)))
        total_expected += len(expected)
        total_failed += failed_after
        total_recovered += len(recovered)

    # summary
    retry = args.retry_missing
    width = 55 if retry else 48
    print("\n" + "=" * width)
    header = f"{'City':<22}{'exp':>6}{'ok':>6}{'fail':>6}"
    if retry:
        header += f"{'recov':>7}"
    print(header)
    print("-" * width)
    for city, exp, ok, fail, recov in rows:
        flag = "  <--" if fail else ""
        line = f"{city:<22}{exp:>6}{ok:>6}{fail:>6}"
        if retry:
            line += f"{recov:>7}"
        print(line + flag)
    print("-" * width)
    total = f"{'TOTAL':<22}{total_expected:>6}{total_expected - total_failed:>6}{total_failed:>6}"
    if retry:
        total += f"{total_recovered:>7}"
    print(total)

    if args.out and failure_rows:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["city", "content_id", "title", "filename", "url", "status"])
            writer.writerows(failure_rows)
        print(f"\nWrote {len(failure_rows)} missing-image rows to {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
