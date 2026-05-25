from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BomItem:
    section: str
    part_id: str
    value: str
    quantity: int
    notes: str = ""
    manufacturer_part_number: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "section": self.section,
            "part_id": self.part_id,
            "value": self.value,
            "quantity": self.quantity,
            "notes": self.notes,
            "manufacturer_part_number": self.manufacturer_part_number,
            "warnings": "; ".join(self.warnings),
        }


@dataclass(slots=True)
class BuildDocument:
    source_name: str
    text: str
    items: list[BomItem]
    warnings: list[str] = field(default_factory=list)
    global_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_name": self.source_name,
            "items": [item.to_dict() for item in self.items],
            "warnings": self.warnings,
            "global_notes": self.global_notes,
        }
