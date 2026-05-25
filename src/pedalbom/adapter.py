from __future__ import annotations

from pathlib import Path

from .models import BuildDocument, BomItem
from .parser import parse_pdf

SECTION_TO_CATEGORY = {
    "resistors": "resistor",
    "capacitors": "capacitor",
    "potentiometers": "potentiometer",
    "semiconductors": "semiconductor",
    "other": "other",
}


def parser_document_to_bom(document: BuildDocument) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "project": {
            "name": infer_project_name(document.source_name),
            "source_document": document.source_name,
        },
        "global_requirements": document.global_notes,
        "items": [item_to_schema(item) for item in document.items],
        "issues": [
            {"severity": "warning", "message": warning, "affected_part_ids": []}
            for warning in document.warnings
        ],
    }


def pdf_to_schema_bom(path: str | Path) -> dict[str, object]:
    return parser_document_to_bom(parse_pdf(path))


def item_to_schema(item: BomItem) -> dict[str, object]:
    schema_item: dict[str, object] = {
        "part_id": item.part_id,
        "value": item.value,
        "quantity": item.quantity,
        "category": SECTION_TO_CATEGORY.get(item.section, "other"),
        "notes": item.notes,
        "requirements": [],
        "source_evidence": " ".join(
            piece for piece in [item.part_id, item.value, str(item.quantity), item.notes] if piece
        ),
        "confidence": 0.75 if item.warnings else 0.9,
    }
    return schema_item


def infer_project_name(source_name: str) -> str:
    stem = Path(source_name).stem.replace("_", " ").replace("-", " ").strip()
    return stem or "Untitled pedal build"
