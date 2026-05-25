from __future__ import annotations

import unittest
from unittest.mock import patch

from pedalbom.mouser import parse_in_stock_quantity, source_bom


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


if __name__ == "__main__":
    unittest.main()
