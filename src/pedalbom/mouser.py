from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

MOUSER_BASE_URL = "https://api.mouser.com/api/v1/search/keyword"


@dataclass(slots=True)
class MouserConfig:
    api_key: str


def load_mouser_config(api_key: str | None = None) -> MouserConfig:
    resolved = api_key or os.environ.get("MOUSER_API_KEY")
    if not resolved:
        raise ValueError("Missing Mouser API key. Set MOUSER_API_KEY or pass --api-key.")
    return MouserConfig(api_key=resolved)


def source_bom(data: dict[str, Any], api_key: str | None = None, limit: int = 5) -> dict[str, Any]:
    config = load_mouser_config(api_key)
    sourced_items: list[dict[str, Any]] = []
    for item in data["items"]:
        query = build_keyword_query(item)
        response = search_keyword(query, config)
        candidates = rank_candidates(item, response.get("SearchResults", {}).get("Parts", []))
        sourced_item = dict(item)
        sourced_item["sourcing"] = {
            "query": query,
            "provider": "mouser",
            "candidates": candidates[:limit],
        }
        sourced_items.append(sourced_item)

    return {
        **data,
        "items": sourced_items,
        "sourcing": {
            "provider": "mouser",
            "note": (
                "Mouser candidates were collected from the Search API. Final manufacturer and Mouser part "
                "numbers require an explicit downstream selection step based on fit, orderability, lifecycle, "
                "lead time, and audio-application suitability."
            ),
        },
    }


def build_keyword_query(item: dict[str, Any]) -> str:
    value = item.get("value", "")
    category = item.get("category", "")
    notes = item.get("notes", "")
    requirements = " ".join(item.get("requirements", []))
    terms = [str(value), str(notes), str(requirements)]
    if category == "resistor":
        terms.append("resistor")
    elif category == "capacitor":
        terms.append("capacitor")
    elif category in {"semiconductor", "ic"}:
        terms.append("through hole")
    elif category == "potentiometer":
        terms.append("potentiometer")
    return " ".join(piece for piece in terms if piece).strip()


def search_keyword(query: str, config: MouserConfig) -> dict[str, Any]:
    params = urllib.parse.urlencode({"apiKey": config.api_key})
    body = json.dumps({"SearchByKeywordRequest": {"keyword": query, "records": 50, "startingRecord": 0}})
    request = urllib.request.Request(
        f"{MOUSER_BASE_URL}?{params}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Mouser API HTTP {exc.code}: {detail}") from exc


def rank_candidates(item: dict[str, Any], parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for part in parts:
        normalized = normalize_mouser_part(part)
        normalized["score"] = score_candidate(item, normalized)
        ranked.append(normalized)
    ranked.sort(key=lambda candidate: candidate["score"], reverse=True)
    return ranked


def normalize_mouser_part(part: dict[str, Any]) -> dict[str, Any]:
    availability = part.get("Availability", "")
    return {
        "mouser_part_number": part.get("MouserPartNumber", ""),
        "manufacturer_part_number": part.get("ManufacturerPartNumber", ""),
        "manufacturer": part.get("Manufacturer", ""),
        "description": part.get("Description", ""),
        "category": part.get("Category", ""),
        "availability": availability,
        "in_stock_quantity": parse_in_stock_quantity(availability),
        "orderable": is_orderable(part),
        "lifecycle_status": part.get("LifecycleStatus", ""),
        "lead_time": part.get("LeadTime", ""),
        "product_detail_url": part.get("ProductDetailUrl", ""),
        "datasheet_url": part.get("DataSheetUrl", ""),
        "min": part.get("Min", ""),
        "mult": part.get("Mult", ""),
        "price_breaks": part.get("PriceBreaks", []),
    }


def score_candidate(item: dict[str, Any], candidate: dict[str, Any]) -> int:
    haystack = " ".join(
        str(candidate.get(field, ""))
        for field in ("manufacturer_part_number", "description", "category", "availability", "lifecycle_status")
    ).lower()
    score = 0
    for token in tokenize(str(item.get("value", ""))):
        if token in haystack:
            score += 5
    category = item.get("category")
    if category == "resistor" and "resistor" in haystack:
        score += 10
    if category == "capacitor" and "capacitor" in haystack:
        score += 10
    if category in {"semiconductor", "ic"} and any(word in haystack for word in ["diode", "transistor", "regulator", "converter"]):
        score += 10
    if "obsolete" in haystack or "not recommended" in haystack:
        score -= 20
    if re.search(r"\b[1-9][0-9,]*\s+in stock\b", haystack):
        score += 8
    elif "in stock" in haystack:
        score += 5
    return score


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in re.split(r"[^A-Za-z0-9.]+", value) if token]


def parse_in_stock_quantity(availability: Any) -> int:
    match = re.search(r"\b([0-9][0-9,]*)\s+in stock\b", str(availability), flags=re.IGNORECASE)
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))


def is_orderable(part: dict[str, Any]) -> bool:
    availability = str(part.get("Availability", "")).lower()
    lifecycle = str(part.get("LifecycleStatus", "")).lower()
    if any(word in lifecycle for word in ("obsolete", "discontinued", "not recommended")):
        return False
    if any(word in availability for word in ("obsolete", "discontinued", "not available")):
        return False
    return "in stock" in availability or bool(part.get("PriceBreaks"))
