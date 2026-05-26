from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from pedalbom.mouser import (
    MouserConfig,
    build_keyword_query,
    format_mouser_http_error,
    parse_in_stock_quantity,
    preferred_manufacturer_filters,
    search_keyword_and_manufacturer,
    search_keyword,
    source_bom,
)


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

        with (
            patch("pedalbom.mouser.search_keyword", return_value=response),
            patch("pedalbom.mouser.search_keyword_and_manufacturer", return_value={"SearchResults": {"Parts": []}}),
        ):
            sourced = source_bom(bom, api_key="test-key", sleeper=lambda _: None)

        item = sourced["items"][0]
        self.assertNotIn("manufacturer_part_number", item)
        self.assertNotIn("mouser_part_number", item)
        self.assertEqual(item["sourcing"]["candidates"][0]["mouser_part_number"], "603-MFR-25FBF52-10K")
        self.assertTrue(item["sourcing"]["candidates"][0]["orderable"])
        self.assertEqual(item["sourcing"]["candidates"][0]["in_stock_quantity"], 3200)

    def test_parse_in_stock_quantity(self) -> None:
        self.assertEqual(parse_in_stock_quantity("12,345 In Stock"), 12345)
        self.assertEqual(parse_in_stock_quantity("Factory lead time 8 weeks"), 0)

    def test_build_keyword_query_sanitizes_mouser_invalid_characters(self) -> None:
        query = build_keyword_query(
            {
                "value": "10kΩ ±1%",
                "quantity": 1,
                "category": "resistor",
                "notes": "metal film (audio) ¼W",
                "requirements": ["through-hole", "low-noise ≤ 50ppm/°C"],
            }
        )

        self.assertEqual(query, "10k ohm 1% metal film resistor through hole")

    def test_build_keyword_query_ignores_non_sourcing_notes(self) -> None:
        query = build_keyword_query(
            {
                "part_id": "R2",
                "value": "390R",
                "quantity": 1,
                "category": "resistor",
                "notes": "Sets max brightness for LED. Adjust to taste. 1/4W through-hole",
                "requirements": ["through-hole", "1/4W"],
            }
        )

        self.assertEqual(query, "390 ohm metal film resistor 1/4W through hole")

    def test_build_keyword_query_never_includes_pcb_designators_or_source_evidence(self) -> None:
        query = build_keyword_query(
            {
                "part_id": "R7, R17",
                "value": "68k",
                "quantity": 2,
                "category": "resistor",
                "notes": "1/4W through-hole",
                "requirements": ["through-hole", "1/4W"],
                "source_evidence": "R7, R17 68k 2 from build table",
            }
        )

        self.assertEqual(query, "68k metal film resistor 1/4W through hole")
        self.assertNotIn("R7", query)
        self.assertNotIn("R17", query)
        self.assertNotIn("build table", query)

    def test_build_capacitor_query_focuses_on_fit(self) -> None:
        query = build_keyword_query(
            {
                "part_id": "C3",
                "value": "10uF",
                "quantity": 1,
                "category": "capacitor",
                "notes": "Non-polar preferred per build notes; if polarised, insert OPPOSITE to silkscreen. 16V min. 2.5mm pitch",
                "requirements": ["through-hole", "non-polar preferred", "16V minimum", "2.5mm pitch"],
            }
        )

        self.assertEqual(query, "10uF non-polar electrolytic capacitor 16v radial 2.5mm pitch through hole")

    def test_preferred_manufacturer_filters_for_film_capacitors(self) -> None:
        filters = preferred_manufacturer_filters(
            {
                "value": "100nF",
                "category": "capacitor",
                "requirements": ["through-hole", "film", "5mm pitch"],
            }
        )

        self.assertEqual(filters, ["WIMA", "KEMET"])

    def test_build_capacitor_query_prefers_electrolytic_requirement_over_noisy_evidence(self) -> None:
        query = build_keyword_query(
            {
                "part_id": "C4, C5, C6, C7, C8",
                "value": "10uF",
                "quantity": 5,
                "category": "capacitor",
                "notes": "Electrolytic, 16V minimum, 2.5mm pitch. C3 is separated as NP variant.",
                "requirements": ["through-hole", "electrolytic", "16V minimum", "2.5mm pitch"],
                "source_evidence": "C3, C4, C5, C6, C7, C8 10uF 5 16v min",
            }
        )

        self.assertEqual(query, "10uF radial electrolytic capacitor 16v 2.5mm pitch through hole")

    def test_build_semiconductor_query_ignores_substitution_notes(self) -> None:
        query = build_keyword_query(
            {
                "part_id": "Q1, Q3",
                "value": "2N3904",
                "quantity": 2,
                "category": "semiconductor",
                "notes": "NPN transistor. Documented as 2N3700 but PCB validated with 2N3904; sub BC557 also listed.",
                "requirements": ["through-hole", "NPN", "TO-92"],
            }
        )

        self.assertEqual(query, "2N3904 NPN transistor TO-92 through hole")

    def test_build_potentiometer_query_expands_taper_semantics(self) -> None:
        query = build_keyword_query(
            {
                "part_id": "VOLUME",
                "value": "A250K",
                "quantity": 1,
                "category": "potentiometer",
                "notes": "Audio taper 250k, board-mounted, 125B enclosure compatible",
                "requirements": ["through-hole", "audio taper", "board-mounted", "9mm or 16mm"],
            }
        )

        self.assertEqual(query, "250K audio taper potentiometer PCB mount through hole")

    def test_build_potentiometer_query_prefers_extracted_taper_semantics(self) -> None:
        query = build_keyword_query(
            {
                "part_id": "GAIN",
                "value": "C10K",
                "quantity": 1,
                "category": "potentiometer",
                "notes": "Log/audio taper 10k, mod to original circuit, board-mounted",
                "requirements": ["through-hole", "audio taper", "board-mounted"],
            }
        )

        self.assertEqual(query, "10K audio taper potentiometer PCB mount through hole")

    def test_forbidden_non_rate_limit_error_mentions_local_terminal(self) -> None:
        message = format_mouser_http_error(403, '{"Message":"IP address not allowed"}')

        self.assertIn("local terminal", message)
        self.assertIn("source IP", message)

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

        messages: list[str] = []

        with (
            patch("pedalbom.mouser.search_keyword", return_value=response) as search,
            patch("pedalbom.mouser.search_keyword_and_manufacturer", return_value={"SearchResults": {"Parts": []}}),
        ):
            sourced = source_bom(bom, api_key="test-key", sleeper=lambda _: None, progress=messages.append)

        self.assertEqual(search.call_count, 1)
        self.assertEqual(sourced["items"][0]["sourcing"]["query"], sourced["items"][1]["sourcing"]["query"])
        self.assertTrue(any("reusing cached search" in message for message in messages))
        self.assertTrue(any("found 0 candidate" in message for message in messages))

    def test_source_bom_cascades_manufacturer_filters_before_generic_search(self) -> None:
        bom = {
            "schema_version": "1.0",
            "project": {"name": "Test Drive"},
            "items": [
                {
                    "part_id": "C1",
                    "value": "100nF",
                    "quantity": 1,
                    "category": "capacitor",
                    "requirements": ["through-hole", "film", "5mm pitch"],
                }
            ],
        }
        wima = {
            "SearchResults": {
                "Parts": [
                    {
                        "MouserPartNumber": "505-MKS2C031001A00K",
                        "ManufacturerPartNumber": "MKS2C031001A00K",
                        "Manufacturer": "WIMA",
                        "Description": "Film Capacitors 100nF 63V 5mm",
                        "Category": "Film Capacitors",
                        "Availability": "100 In Stock",
                    }
                ]
            }
        }

        with (
            patch("pedalbom.mouser.search_keyword") as generic_search,
            patch("pedalbom.mouser.search_keyword_and_manufacturer", return_value=wima) as mfr_search,
        ):
            sourced = source_bom(bom, api_key="test-key", sleeper=lambda _: None)

        item = sourced["items"][0]
        self.assertEqual(item["sourcing"]["manufacturer_filters"], ["WIMA", "KEMET"])
        self.assertEqual(item["sourcing"]["search_strategy"], "manufacturer:WIMA")
        self.assertEqual(mfr_search.call_count, 1)
        generic_search.assert_not_called()
        self.assertTrue(
            any(candidate["manufacturer"] == "WIMA" for candidate in item["sourcing"]["candidates"])
        )

    def test_source_bom_falls_back_to_generic_search_after_empty_manufacturer_filters(self) -> None:
        bom = {
            "schema_version": "1.0",
            "project": {"name": "Test Drive"},
            "items": [
                {
                    "part_id": "C1",
                    "value": "100nF",
                    "quantity": 1,
                    "category": "capacitor",
                    "requirements": ["through-hole", "film", "5mm pitch"],
                }
            ],
        }
        generic = {"SearchResults": {"Parts": [{"MouserPartNumber": "123", "Description": "100nF Film Capacitor"}]}}

        with (
            patch("pedalbom.mouser.search_keyword", return_value=generic) as generic_search,
            patch(
                "pedalbom.mouser.search_keyword_and_manufacturer",
                return_value={"SearchResults": {"Parts": []}},
            ) as mfr_search,
        ):
            sourced = source_bom(bom, api_key="test-key", sleeper=lambda _: None)

        self.assertEqual(mfr_search.call_count, 2)
        self.assertEqual(generic_search.call_count, 1)
        self.assertEqual(sourced["items"][0]["sourcing"]["search_strategy"], "generic")

    def test_source_bom_treats_null_mouser_search_results_as_empty(self) -> None:
        bom = {
            "schema_version": "1.0",
            "project": {"name": "Test Drive"},
            "items": [
                {
                    "part_id": "Footswitch",
                    "value": "3PDT",
                    "quantity": 1,
                    "category": "switch",
                    "requirements": ["through-hole", "3PDT", "solder lug"],
                }
            ],
        }

        with (
            patch("pedalbom.mouser.search_keyword", return_value={"SearchResults": None}) as generic_search,
            patch(
                "pedalbom.mouser.search_keyword_and_manufacturer",
                return_value={"Errors": [], "SearchResults": None},
            ) as mfr_search,
        ):
            sourced = source_bom(bom, api_key="test-key", sleeper=lambda _: None)

        self.assertEqual(mfr_search.call_count, 2)
        self.assertEqual(generic_search.call_count, 1)
        self.assertEqual(sourced["items"][0]["sourcing"]["candidates"], [])
        self.assertEqual(sourced["items"][0]["sourcing"]["search_strategy"], "generic")

    def test_search_keyword_uses_in_stock_search_option(self) -> None:
        response = FakeResponse(b'{"SearchResults":{"Parts":[]}}')

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = search_keyword("10k resistor", MouserConfig(api_key="test-key"))

        request = urlopen.call_args.args[0]
        body = request.data.decode("utf-8")
        self.assertEqual(result, {"SearchResults": {"Parts": []}})
        self.assertIn('"searchOptions": "InStock"', body)

    def test_search_keyword_and_manufacturer_uses_v2_request_shape(self) -> None:
        response = FakeResponse(b'{"SearchResults":{"Parts":[]}}')

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = search_keyword_and_manufacturer(
                "100nF film capacitor 5mm pitch",
                "WIMA",
                MouserConfig(api_key="test-key"),
            )

        request = urlopen.call_args.args[0]
        body = request.data.decode("utf-8")
        self.assertIn("/api/v2/search/keywordandmanufacturer", request.full_url)
        self.assertEqual(result, {"SearchResults": {"Parts": []}})
        self.assertIn("SearchByKeywordMfrNameRequest", body)
        self.assertIn('"manufacturerName": "WIMA"', body)
        self.assertIn('"searchOptions": "InStock"', body)

    def test_source_bom_error_includes_item_and_query(self) -> None:
        bom = {
            "schema_version": "1.0",
            "project": {"name": "Test Drive"},
            "items": [{"part_id": "C1", "value": "10uF", "quantity": 1, "category": "capacitor"}],
        }

        with patch("pedalbom.mouser.search_keyword", side_effect=RuntimeError("Mouser API HTTP 400")):
            with self.assertRaisesRegex(RuntimeError, r"C1.*10uF capacitor"):
                source_bom(bom, api_key="test-key", sleeper=lambda _: None)

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
        messages: list[str] = []

        with patch("urllib.request.urlopen", side_effect=[rate_limit_error, ok_response]) as urlopen:
            result = search_keyword(
                "10k resistor",
                MouserConfig(api_key="test-key"),
                max_retries=1,
                retry_delay=0.5,
                sleeper=sleeps.append,
                progress=messages.append,
            )

        self.assertEqual(result, {"SearchResults": {"Parts": []}})
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(sleeps, [0.5])
        self.assertTrue(any("rate limit" in message.lower() for message in messages))


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
