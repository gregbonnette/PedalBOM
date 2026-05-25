from __future__ import annotations

import unittest

from pedalbom.adapter import parser_document_to_bom
from pedalbom.models import BomItem, BuildDocument
from pedalbom.schema import validate_bom


class SchemaTests(unittest.TestCase):
    def test_valid_schema_bom_passes(self) -> None:
        bom = {
            "schema_version": "1.0",
            "project": {"name": "Test Drive"},
            "global_requirements": ["1/4W resistors"],
            "items": [
                {
                    "part_id": "R1",
                    "value": "10k",
                    "quantity": 1,
                    "category": "resistor",
                    "notes": "Metal film resistor, 1/4W",
                    "requirements": ["through-hole"],
                    "source_evidence": "R1 10k Metal film resistor, 1/4W",
                    "confidence": 0.99,
                }
            ],
            "issues": [],
        }

        result = validate_bom(bom)

        self.assertTrue(result.ok)
        self.assertEqual(result.errors, [])

    def test_missing_required_fields_fail(self) -> None:
        result = validate_bom({"schema_version": "1.0", "project": {"name": "Bad"}, "items": [{}]})

        self.assertFalse(result.ok)
        self.assertTrue(any("part_id" in error for error in result.errors))
        self.assertTrue(any("quantity" in error for error in result.errors))

    def test_parser_adapter_outputs_schema_bom(self) -> None:
        document = BuildDocument(
            source_name="sample.pdf",
            text="",
            global_notes=["5mm film caps"],
            items=[BomItem(section="resistors", part_id="R1", value="10k", quantity=1)],
        )

        bom = parser_document_to_bom(document)
        result = validate_bom(bom)

        self.assertTrue(result.ok)
        self.assertEqual(bom["items"][0]["category"], "resistor")
        self.assertEqual(bom["global_requirements"], ["5mm film caps"])


if __name__ == "__main__":
    unittest.main()
