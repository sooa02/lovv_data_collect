"""Tests for the KR domain loader Lambda handler."""

from __future__ import annotations

import io
import json
import sys
import types

import pytest

from kr_details_pipeline.handlers import domain_loader_handler


class FakeS3Client:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.put_calls: list[dict] = []

    def get_object(self, **kwargs):  # noqa: ANN001, ARG002
        return {"Body": io.BytesIO(json.dumps(self.payload).encode("utf-8"))}

    def put_object(self, **kwargs):  # noqa: ANN001
        self.put_calls.append(kwargs)
        return {}


class FakeDynamoClient:
    pass


class FakeBoto3:
    def __init__(self, s3: FakeS3Client, ddb: FakeDynamoClient) -> None:
        self.s3 = s3
        self.ddb = ddb

    def client(self, service_name: str):  # noqa: ANN201
        if service_name == "s3":
            return self.s3
        if service_name == "dynamodb":
            return self.ddb
        raise ValueError(service_name)


def _payload() -> dict:
    return {
        "meta": {
            "city_name_en": "Andong",
            "city_name_ko": "안동시",
            "province": "경상북도",
            "lDongRegnCd": "47",
            "lDongSignguCd": "170",
        },
        "attractions": [
            {
                "contentid": "100",
                "contenttypeid": "12",
                "title": "하회마을",
                "mapx": "128.6",
                "mapy": "36.5",
                "_assigned_theme": "history",
            }
        ],
    }


def test_handler_returns_partial_status_when_one_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3Client(_payload())
    ddb = FakeDynamoClient()
    fake_boto3 = FakeBoto3(s3, ddb)
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=fake_boto3.client))
    write_calls: list[dict] = []

    def fake_write_item(client, table_name, item):  # noqa: ANN001
        write_calls.append({"client": client, "table_name": table_name, "item": item})
        if len(write_calls) == 2:
            raise RuntimeError("forced write failure")

    monkeypatch.setattr(domain_loader_handler.load, "_write_item", fake_write_item)

    response = domain_loader_handler.handler(
        {
            "bucket": "bucket",
            "raw_key": "raw/KR/details/20260609/Andong.json",
            "table_name": "TourKoreaDomainData",
            "write_processed": True,
        },
        context=None,
    )

    assert response["statusCode"] == 207
    assert response["summary"]["status"] == "partial"
    assert response["summary"]["loaded"] == 1
    assert response["summary"]["load_failed"] == 1
    assert response["failures"][0]["entity_id"] == "ATT-100"
    assert "RuntimeError: forced write failure" == response["failures"][0]["error"]
    assert len(s3.put_calls) == 1
    assert s3.put_calls[0]["Key"] == "processed/KR/domain/20260609/Andong/summary.json"


def test_handler_extracts_s3_event_record(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3Client(_payload())
    ddb = FakeDynamoClient()
    fake_boto3 = FakeBoto3(s3, ddb)
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=fake_boto3.client))
    write_calls: list[dict] = []

    def fake_write_item(client, table_name, item):  # noqa: ANN001
        write_calls.append({"client": client, "table_name": table_name, "item": item})

    monkeypatch.setattr(domain_loader_handler.load, "_write_item", fake_write_item)

    response = domain_loader_handler.handler(
        {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": "bucket"},
                        "object": {"key": "raw/KR/details/20260609/Andong.json"},
                    }
                }
            ],
            "table_name": "TourKoreaDomainData",
            "write_processed": False,
        },
        context=None,
    )

    assert response["statusCode"] == 200
    assert response["summary"]["loaded"] == 2
    assert response["summary"]["load_failed"] == 0
    assert s3.put_calls == []
