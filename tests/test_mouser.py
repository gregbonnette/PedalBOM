from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from pedalbom.mouser import MouserConfig, parse_in_stock_quantity, search_keyword, source_bom


class MouserTests(unittest.TestCase):
    def test_source_bom_collects_candidates_without_selecting_part_numbers(self) -> None:
        bom = {
            "schema_version": "1.0",
            "project": {"name": "Test Drive"},
            "items": [
                {
                    "part_id": "R1",
                    "value": "10k",
                    "quantity": 1,
                    "category": "resistor",
                    "requirements": ["through-hole", "1/4W"],
                    "source_evidence": "R1 10k 1/4W resistor",
                }
            ],
        }
        response = {
            "SearchResults": {
                "Parts": [
                    {
                        "MouserPartNumber": "603-MFR-25FBF52-10K",
                        "ManufacturerPartNumber": "MFR-25FBF52-10K",
                        "Manufacturer": "YAGEO",
                        "Description": "Metal Film Resistors 10K 1/4W 1%",
                        "Category": "Resistors",
                        "Availability": "3,200 In Stock",
                        "LifecycleStatus": "Active",
                        "PriceBreaks": [{"Quantity": 1, "Price": "$0.10"}],
                    }
                ]
            }
        }

        with patch("pedalbom.mouser.search_keyword", return_value=response):
            sourced = source_bom(bom, api_key="test-key")

        item = sourced["items"][0]
        self.assertNotIn("manufacturer_part_number", item)
        self.assertNotIn("mouser_part_number", item)
        self.assertEqual(item["sourcing"]["candidates"][0]["mouser_part_number"], "603-MFR-25FBF52-10K")
        self.assertTrue(item["sourcing"]["candidates"][0]["orderable"])
        self.assertEqual(item["sourcing"]["candidates"][0]["in_stock_quantity"], 3200)

    def test_parse_in_stock_quantity(self) -> None:
        self.assertEqual(parse_in_stock_quantity("12,345 In Stock"), 12345)
        self.assertEqual(parse_in_stock_quantity("Factory lead time 8 weeks"), 0)

    def test_source_bom_reuses_identical_search_queries(self) -> None:
        bom = {
            "schema_version": "1.0",
            "project": {"name": "Test Drive"},
            "items": [
                {"part_id": "R1", "value": "10k", "quantity": 1, "category": "resistor"},
                {"part_id": "R2", "value": "10k", "quantity": 1, "category": "resistor"},
            ],
        }
        response = {"SearchResults": {"Parts": []}}

        with patch("pedalbom.mouser.search_keyword", return_value=response) as search:
            sourced = source_bom(bom, api_key="test-key", sleeper=lambda _: None)

        self.assertEqual(search.call_count, 1)
        self.assertEqual(sourced["items"][0]["sourcing"]["query"], sourced["items"][1]["sourcing"]["query"])

    def test_search_keyword_retries_rate_limit_responses(self) -> None:
        rate_limit_error = urllib.error.HTTPError(
            url="https://api.mouser.test",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=FakeResponse(
                b'{"Errors":[{"Code":"TooManyRequests","Message":"Maximum calls per minute exceeded."}]}'
            ),
        )
        ok_response = FakeResponse(b'{"SearchResults":{"Parts":[]}}')
        sleeps: list[float] = []

        with patch("urllib.request.urlopen", side_effect=[rate_limit_error, ok_response]) as urlopen:
            result = search_keyword(
                "10k resistor",
                MouserConfig(api_key="test-key"),
                max_retries=1,
                retry_delay=0.5,
                sleeper=sleeps.append,
            )

        self.assertEqual(result, {"SearchResults": {"Parts": []}})
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(sleeps, [0.5])


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        return None

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
