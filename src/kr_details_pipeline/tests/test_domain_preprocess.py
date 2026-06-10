"""Tests for KR domain-specific preprocessing."""

from __future__ import annotations

import json
from pathlib import Path

from kr_details_pipeline import domain_preprocess


def _base_payload() -> dict:
    return {
        "meta": {
            "city_name_en": "Andong",
            "city_name_ko": "안동시",
            "province": "경상북도",
            "lDongRegnCd": "47",
            "lDongSignguCd": "170",
            "sigungus_included": ["안동시"],
            "scraped_at": "2026-06-09T00:00:00Z",
        },
        "attractions": [],
        "festivals": [],
        "visitor_statistics": {
            "year": 2025,
            "annual_totals": {"total_visitors": 1200},
            "annual_daily_averages": {"total_daily_avg": 100},
            "monthly_statistics": [
                {
                    "month": "2025-01",
                    "days": 31,
                    "locals_total": 100,
                    "locals_daily_avg": 3.2,
                    "out_of_town_total": 200,
                    "out_of_town_daily_avg": 6.5,
                    "foreigners_total": 10,
                    "foreigners_daily_avg": 0.3,
                    "total_visitors": 310,
                    "total_daily_avg": 10,
                }
            ],
        },
    }


def test_preprocess_classifies_domains_and_projects_allowed_columns() -> None:
    payload = _base_payload()
    payload["attractions"] = [
        {
            "contentid": "100",
            "contenttypeid": "39",
            "title": "안동식당",
            "mapx": "128.7",
            "mapy": "36.5",
            "detail": {
                "common": {"overview": "restaurant overview", "tel": "054-000-0000"},
                "intro": {
                    "opentimefood": "09:00-18:00",
                    "restdatefood": "Monday",
                    "treatmenu": "간고등어",
                    "parkingfood": "가능",
                    "eventstartdate": "20250101",
                },
            },
        },
        {
            "contentid": "200",
            "contenttypeid": "12",
            "title": "하회마을",
            "mapx": "128.6",
            "mapy": "36.5",
            "_assigned_theme": "history",
            "detail": {"intro": {"infocenterculture": "054-111-1111", "usetime": "10:00-17:00"}},
        },
        {
            "contentid": "300",
            "contenttypeid": "25",
            "title": "검수대상",
            "mapx": "128.6",
            "mapy": "36.5",
        },
    ]
    payload["festivals"] = [
        {
            "contentid": "400",
            "title": "안동축제",
            "mapx": "128.7",
            "mapy": "36.4",
            "detail": {
                "intro": {
                    "eventstartdate": "20251001",
                    "eventenddate": "20251003",
                    "eventplace": "탈춤공원",
                    "sponsor1": "안동시",
                    "usetimefestival": "무료",
                    "opentimefood": "should not leak",
                }
            },
        }
    ]

    result = domain_preprocess.preprocess_city_payload(payload, source_key="raw/key.json", table_name="TourKoreaDomainData")

    assert result["summary"]["restaurants"] == 1
    assert result["summary"]["attractions"] == 1
    assert result["summary"]["festivals"] == 1
    assert result["summary"]["visitor_statistics"] == 1
    assert result["summary"]["review"] == 1
    assert result["summary"]["failed"] == 0
    assert result["summary"]["load_items"] == 5

    restaurant = result["restaurants"][0]
    assert restaurant["SK"] == "RESTAURANT#100"
    assert restaurant["entity_id"] == "REST-100"
    assert restaurant["phone"] == "054-000-0000"
    assert "event_start_date" not in restaurant

    attraction = result["attractions"][0]
    assert attraction["SK"] == "ATTRACTION#200"
    assert attraction["entity_id"] == "ATT-200"
    assert attraction["phone"] == "054-111-1111"
    assert "signature_menu" not in attraction

    festival = result["festivals"][0]
    assert festival["SK"] == "FESTIVAL#400"
    assert festival["entity_id"] == "FEST-400"
    assert festival["event_start_date"] == "2025-10-01"
    assert festival["season"] == "autumn"
    assert "opening_hours" not in festival

    city_item = result["city_metadata"][0]
    assert city_item["province_key"] == "PROVINCE#경상북도"
    assert city_item["city_key"] == "CITY#Andong"

    stat_item = result["visitor_statistics"][0]
    assert stat_item["SK"] == "STAT#202501"
    assert stat_item["domain_sort_key"] == "STAT#202501"


def test_preprocess_routes_missing_required_fields_to_failed() -> None:
    payload = _base_payload()
    payload["attractions"] = [
        {
            "contentid": "500",
            "contenttypeid": "12",
            "mapx": "128.6",
            "mapy": "36.5",
        }
    ]

    result = domain_preprocess.preprocess_city_payload(payload, source_key="raw/key.json", table_name="TourKoreaDomainData")

    assert result["summary"]["failed"] == 1
    assert result["summary"]["attractions"] == 0
    assert result["failed"][0]["quality_status"] == "failed"
    assert "missing_title" in result["failed"][0]["review_queues"]


def test_write_preprocess_output_writes_domain_files(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["attractions"] = [
        {
            "contentid": "100",
            "contenttypeid": "39",
            "title": "안동식당",
            "mapx": "128.7",
            "mapy": "36.5",
            "detail": {"common": {"tel": "054-000-0000"}},
        }
    ]
    result = domain_preprocess.preprocess_city_payload(payload, source_key="raw/key.json", table_name="TourKoreaDomainData")

    domain_preprocess.write_preprocess_output(result, tmp_path)

    assert (tmp_path / "normalized" / "restaurants.jsonl").exists()
    assert (tmp_path / "load" / "tour_korea_domain_items.jsonl").exists()
    assert (tmp_path / "quality" / "summary.json").exists()
    summary = json.loads((tmp_path / "quality" / "summary.json").read_text(encoding="utf-8"))
    assert summary["restaurants"] == 1
