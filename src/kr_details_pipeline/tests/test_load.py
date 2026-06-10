"""Tests for KR load helpers."""

from __future__ import annotations

import unittest

from kr_details_pipeline import load


class FakeDynamoClient:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []

    def put_item(self, **kwargs):  # noqa: ANN001
        self.put_calls.append(kwargs)
        return {"ConsumedCapacity": {"CapacityUnits": 1}}


class LoadTest(unittest.TestCase):
    def test_load_passed_records_writes_city_and_entities(self) -> None:
        payload = {
            "status": "passed",
            "city_record": {
                "city_id": "KR-47-001",
                "city_name_en": "ANDONG",
                "city_name_ko": "안동시",
                "province": "경북",
                "lDongRegnCd": "47",
                "lDongSignguCd": "001",
            },
            "records": [
                {
                    "entity_type": "attraction",
                    "entity_id": "ATT-1001",
                    "content_id": "1001",
                    "SK": "ATTRACTION#1001",
                    "quality_status": "passed",
                },
                {
                    "entity_type": "visitor_statistics",
                    "entity_id": "KR-STAT-KR-47-001-202601",
                    "month": "202601",
                    "SK": "STAT#202601",
                    "quality_status": "passed",
                },
            ],
        }
        fake_client = FakeDynamoClient()
        result = load.load_processed_payload(payload, "TourKoreaDomainData", fake_client)

        self.assertEqual(3, result.passed)
        self.assertEqual(0, result.failed)
        self.assertEqual(3, len(fake_client.put_calls))


if __name__ == "__main__":
    unittest.main()
