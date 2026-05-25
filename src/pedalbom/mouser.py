from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

MOUSER_BASE_URL = "https://api.mouser.com/api/v1/search/keyword"
ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class MouserConfig:
    api_key: str


def load_mouser_config(api_key: str | None = None) -> MouserConfig:
    resolved = api_key or os.environ.get("MOUSER_API_KEY")
    if not resolved:
        raise ValueError("Missing Mouser API key. Set MOUSER_API_KEY or pass --api-key.")
    return MouserConfig(api_key=resolved)


def has_mouser_api_key(api_key: str | None = None) -> bool:
    return bool(api_key or os.environ.get("MOUSER_API_KEY"))


def source_bom(
    data: dict[str, Any],
    api_key: str | None = None,
    limit: int = 5,
    rate_limit_delay: float = 2.1,
    max_retries: int = 2,
    retry_delay: float = 60.0,
    sleeper: Callable[[float], None] = time.sleep,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    config = load_mouser_config(api_key)
    sourced_items: list[dict[str, Any]] = []
    responses_by_query: dict[str, dict[str, Any]] = {}
    unique_call_count = 0
    total_items = len(data["items"])
    emit_progress(progress, f"Sourcing {total_items} BOM item(s) with Mouser.")
    for index, item in enumerate(data["items"], start=1):
        query = build_keyword_query(item)
        part_id = item.get("part_id", f"item {index}")
        if query in responses_by_query:
            emit_progress(progress, f"[{index}/{total_items}] {part_id}: reusing cached search for {query!r}.")
            response = responses_by_query[query]
        else:
            if unique_call_count and rate_limit_delay > 0:
                emit_progress(progress, f"[{index}/{total_items}] Waiting {rate_limit_delay:g}s before next Mouser call.")
                sleeper(rate_limit_delay)
            emit_progress(progress, f"[{index}/{total_items}] {part_id}: searching Mouser for {query!r}.")
            try:
                response = search_keyword(
                    query,
                    config,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    sleeper=sleeper,
                    progress=progress,
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Failed Mouser search for item {index}/{total_items} ({part_id}) with query {query!r}: {exc}"
                ) from exc
            responses_by_query[query] = response
            unique_call_count += 1
        candidates = rank_candidates(item, response.get("SearchResults", {}).get("Parts", []))
        emit_progress(
            progress,
            f"[{index}/{total_items}] {part_id}: found {len(candidates)} candidate(s), keeping {min(limit, len(candidates))}.",
        )
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
                "lead time, and audio-application suitability. Identical search queries were cached within "
                "this run to reduce API usage."
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
    return sanitize_keyword_query(" ".join(piece for piece in terms if piece))


def sanitize_keyword_query(query: str) -> str:
    query = query.replace("Ω", " ohm ").replace("µ", "u").replace("μ", "u")
    query = query.replace("±", " ").replace("≤", " ").replace("≥", " ")
    query = query.replace("¼", "1/4").replace("½", "1/2")
    query = re.sub(r"[^\w\s./%+-]", " ", query, flags=re.ASCII)
    query = re.sub(r"\s+", " ", query).strip()
    query = re.sub(r"\s*/\s*", "/", query)
    return query


def search_keyword(
    query: str,
    config: MouserConfig,
    max_retries: int = 2,
    retry_delay: float = 60.0,
    sleeper: Callable[[float], None] = time.sleep,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    params = urllib.parse.urlencode({"apiKey": config.api_key})
    body = json.dumps({"SearchByKeywordRequest": {"keyword": query, "records": 50, "startingRecord": 0}})
    request = urllib.request.Request(
        f"{MOUSER_BASE_URL}?{params}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            exc.close()
            if is_rate_limit_error(exc.code, detail) and attempt < max_retries:
                emit_progress(
                    progress,
                    f"Mouser rate limit hit; waiting {retry_delay:g}s before retry {attempt + 1}/{max_retries}.",
                )
                sleeper(retry_delay)
                continue
            raise RuntimeError(format_mouser_http_error(exc.code, detail)) from exc
    raise RuntimeError("Mouser API search failed after retries.")


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


def is_rate_limit_error(status_code: int, detail: str) -> bool:
    return status_code in {403, 429} and (
        "TooManyRequests" in detail
        or "Maximum calls per minute exceeded" in detail
        or "rate limit" in detail.lower()
    )


def format_mouser_http_error(status_code: int, detail: str) -> str:
    message = f"Mouser API HTTP {status_code}: {detail}"
    if status_code == 400 and "InvalidCharacters" in detail:
        message += "\nMouser rejected the search keyword. The failing item and sanitized query are shown above."
    if status_code == 403 and not is_rate_limit_error(status_code, detail):
        message += (
            "\nMouser rejected this request. If you are running from Claude or another hosted agent, "
            "run `pedalbom source` from the user's local terminal instead; Mouser API access can be "
            "restricted by source IP address."
        )
    return message


def emit_progress(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
