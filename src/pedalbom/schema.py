from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
CATEGORIES = {
    "resistor",
    "capacitor",
    "potentiometer",
    "semiconductor",
    "ic",
    "socket",
    "switch",
    "jack",
    "hardware",
    "other",
}


@dataclass(slots=True)
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def schema_text() -> str:
    return (files("pedalbom") / "schema" / "bom.schema.json").read_text(encoding="utf-8")


def load_bom(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(data: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_bom(data: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()
    if not isinstance(data, dict):
        result.errors.append("BOM must be a JSON object.")
        return result

    require(data, "schema_version", result, "root")
    require(data, "project", result, "root")
    require(data, "items", result, "root")

    if data.get("schema_version") != SCHEMA_VERSION:
        result.errors.append(f"schema_version must be {SCHEMA_VERSION!r}.")

    project = data.get("project")
    if not isinstance(project, dict):
        result.errors.append("project must be an object.")
    elif not nonempty_string(project.get("name")):
        result.errors.append("project.name is required.")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        result.errors.append("items must be a non-empty array.")
        return result

    seen: dict[str, int] = {}
    for index, item in enumerate(items):
        path = f"items[{index}]"
        if not isinstance(item, dict):
            result.errors.append(f"{path} must be an object.")
            continue
        validate_item(item, path, result)
        part_id = str(item.get("part_id", "")).strip()
        if part_id:
            if part_id in seen:
                result.warnings.append(f"{path}.part_id duplicates items[{seen[part_id]}]: {part_id}")
            seen[part_id] = index

    issues = data.get("issues", [])
    if issues is not None and not isinstance(issues, list):
        result.errors.append("issues must be an array when present.")

    return result


def validate_item(item: dict[str, Any], path: str, result: ValidationResult) -> None:
    for field_name in ("part_id", "value", "quantity", "category"):
        require(item, field_name, result, path)
    if not nonempty_string(item.get("part_id")):
        result.errors.append(f"{path}.part_id must be a non-empty string.")
    if not nonempty_string(item.get("value")):
        result.errors.append(f"{path}.value must be a non-empty string.")
    if not isinstance(item.get("quantity"), int) or item.get("quantity", 0) < 1:
        result.errors.append(f"{path}.quantity must be an integer >= 1.")
    if item.get("category") not in CATEGORIES:
        result.errors.append(f"{path}.category must be one of: {', '.join(sorted(CATEGORIES))}.")

    confidence = item.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, int | float) or confidence < 0 or confidence > 1
    ):
        result.errors.append(f"{path}.confidence must be a number from 0 to 1.")

    for forbidden in ("manufacturer_part_number", "mouser_part_number"):
        value = item.get(forbidden)
        if value and not item.get("source_evidence"):
            result.warnings.append(
                f"{path}.{forbidden} is populated; ensure it came directly from source evidence or sourcing output."
            )

    if not item.get("source_evidence"):
        result.warnings.append(f"{path}.source_evidence is missing.")

    if looks_like_multiple_designators(str(item.get("part_id", ""))) and item.get("quantity") == 1:
        result.warnings.append(f"{path}.part_id may contain multiple designators but quantity is 1.")


def require(data: dict[str, Any], field_name: str, result: ValidationResult, path: str) -> None:
    if field_name not in data:
        result.errors.append(f"{path}.{field_name} is required.")


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def looks_like_multiple_designators(value: str) -> bool:
    return bool(re.search(r"[, ]+[A-Z]+\d+", value, flags=re.IGNORECASE))
