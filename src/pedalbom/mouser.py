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

MOUSER_KEYWORD_URL = "https://api.mouser.com/api/v1/search/keyword"
MOUSER_KEYWORD_AND_MANUFACTURER_URL = "https://api.mouser.com/api/v2/search/keywordandmanufacturer"
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
    limit: int = 10,
    rate_limit_delay: float = 2.1,
    max_retries: int = 2,
    retry_delay: float = 60.0,
    sleeper: Callable[[float], None] = time.sleep,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    config = load_mouser_config(api_key)
    sourced_items: list[dict[str, Any]] = []
    responses_by_search: dict[tuple[str, str], dict[str, Any]] = {}
    unique_call_count = 0
    total_items = len(data["items"])
    emit_progress(progress, f"Sourcing {total_items} BOM item(s) with Mouser.")
    for index, item in enumerate(data["items"], start=1):
        query = build_keyword_query(item)
        part_id = item.get("part_id", f"item {index}")
        manufacturer_filters = preferred_manufacturer_filters(item)
        parts: list[dict[str, Any]] = []
        used_search_label = "generic"
        for manufacturer in manufacturer_filters:
            mfr_cache_key = (manufacturer, query)
            if mfr_cache_key in responses_by_search:
                emit_progress(
                    progress,
                    f"[{index}/{total_items}] {part_id}: reusing cached {manufacturer} search for {query!r}.",
                )
                mfr_response = responses_by_search[mfr_cache_key]
            else:
                if rate_limit_delay > 0:
                    emit_progress(
                        progress,
                        f"[{index}/{total_items}] Waiting {rate_limit_delay:g}s before next Mouser call.",
                    )
                    sleeper(rate_limit_delay)
                emit_progress(
                    progress,
                    f"[{index}/{total_items}] {part_id}: searching Mouser V2 for {query!r} by {manufacturer}.",
                )
                try:
                    mfr_response = search_keyword_and_manufacturer(
                        query,
                        manufacturer,
                        config,
                        max_retries=max_retries,
                        retry_delay=retry_delay,
                        sleeper=sleeper,
                        progress=progress,
                    )
                except RuntimeError as exc:
                    raise RuntimeError(
                        f"Failed Mouser manufacturer search for item {index}/{total_items} ({part_id}) "
                        f"with query {query!r} and manufacturer {manufacturer!r}: {exc}"
                    ) from exc
                responses_by_search[mfr_cache_key] = mfr_response
                unique_call_count += 1
            mfr_parts = response_parts(mfr_response)
            if mfr_parts:
                parts = mfr_parts
                used_search_label = f"manufacturer:{manufacturer}"
                emit_progress(
                    progress,
                    f"[{index}/{total_items}] {part_id}: using {len(parts)} {manufacturer} candidate(s).",
                )
                break

        if not parts:
            generic_cache_key = ("", query)
            if generic_cache_key in responses_by_search:
                emit_progress(progress, f"[{index}/{total_items}] {part_id}: reusing cached search for {query!r}.")
                response = responses_by_search[generic_cache_key]
            else:
                if unique_call_count and rate_limit_delay > 0:
                    emit_progress(
                        progress,
                        f"[{index}/{total_items}] Waiting {rate_limit_delay:g}s before next Mouser call.",
                    )
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
                responses_by_search[generic_cache_key] = response
                unique_call_count += 1
            parts = response_parts(response)

        candidates = rank_candidates(item, dedupe_parts(parts))
        emit_progress(
            progress,
            f"[{index}/{total_items}] {part_id}: found {len(candidates)} candidate(s) via {used_search_label}, keeping {min(limit, len(candidates))}.",
        )
        sourced_item = dict(item)
        sourced_item["sourcing"] = {
            "query": query,
            "provider": "mouser",
            "manufacturer_filters": manufacturer_filters,
            "search_strategy": used_search_label,
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
                "this run to reduce API usage. Curated manufacturer-filtered V2 searches cascade through "
                "preferred manufacturers before falling back to generic keyword search."
            ),
        },
    }


def build_keyword_query(item: dict[str, Any]) -> str:
    category = item.get("category", "")
    if category == "resistor":
        return build_resistor_query(item)
    if category == "capacitor":
        return build_capacitor_query(item)
    if category == "potentiometer":
        return build_potentiometer_query(item)
    if category in {"semiconductor", "ic"}:
        return build_semiconductor_query(item)
    if category == "switch":
        return build_switch_query(item)
    return build_generic_query(item)


def build_resistor_query(item: dict[str, Any]) -> str:
    terms = [normalize_component_value(item.get("value", "")), "metal film resistor"]
    if has_requirement(item, "1/4W") or has_requirement(item, "1/4 W"):
        terms.append("1/4W")
    if has_requirement(item, "through-hole"):
        terms.append("through hole")
    return compact_keyword_query(terms)


def build_capacitor_query(item: dict[str, Any]) -> str:
    terms = [normalize_component_value(item.get("value", ""))]
    text = item_text(item)
    requirements = requirements_text(item)
    if "film" in text:
        terms.extend(["film capacitor", first_match(text, r"\b\d+(?:\.\d+)?\s*mm\s+pitch\b")])
    elif "electrolytic" in requirements:
        terms.extend(["radial electrolytic capacitor", first_match(text, r"\b\d+(?:\.\d+)?\s*V\b")])
        terms.append(first_match(text, r"\b\d+(?:\.\d+)?\s*mm\s+pitch\b"))
    elif "non-polar" in requirements or "non polar" in requirements or re.search(r"\bNP\b", text, flags=re.IGNORECASE):
        terms.extend(["non-polar electrolytic capacitor", first_match(text, r"\b\d+(?:\.\d+)?\s*V\b"), "radial"])
        terms.append(first_match(text, r"\b\d+(?:\.\d+)?\s*mm\s+pitch\b"))
    elif "electrolytic" in text:
        terms.extend(["radial electrolytic capacitor", first_match(text, r"\b\d+(?:\.\d+)?\s*V\b")])
        terms.append(first_match(text, r"\b\d+(?:\.\d+)?\s*mm\s+pitch\b"))
    else:
        terms.append("capacitor")
    if has_requirement(item, "through-hole"):
        terms.append("through hole")
    return compact_keyword_query(terms)


def build_potentiometer_query(item: dict[str, Any]) -> str:
    value = str(item.get("value", ""))
    taper, resistance = split_potentiometer_value(value)
    text = item_text(item)
    if "trimmer" in text or "3362" in text:
        return compact_keyword_query([resistance or value, "3362", "trimmer potentiometer", "through hole"])
    terms = [resistance or value, potentiometer_taper(item, taper), "potentiometer"]
    if "board-mounted" in text or "board mounted" in text:
        terms.append("PCB mount")
    if has_requirement(item, "through-hole"):
        terms.append("through hole")
    return compact_keyword_query(terms)


def build_semiconductor_query(item: dict[str, Any]) -> str:
    value = str(item.get("value", ""))
    text = item_text(item)
    if "LED" in value.upper() or "led" in text:
        return compact_keyword_query([value, "through hole"])
    if "diode" in text or value.upper().startswith("1N"):
        terms = [value, "diode"]
        if "schottky" in text:
            terms.append("schottky")
        if has_requirement(item, "through-hole"):
            terms.append("through hole")
        package = first_requirement(item, ["DO-35", "DO-41", "TO-92"])
        terms.append(package)
        return compact_keyword_query(terms)
    terms = [value]
    if "NPN" in item_text_case_sensitive(item):
        terms.append("NPN transistor")
    elif "PNP" in item_text_case_sensitive(item):
        terms.append("PNP transistor")
    else:
        terms.append("transistor")
    package = first_requirement(item, ["TO-92"])
    terms.append(package)
    if has_requirement(item, "through-hole"):
        terms.append("through hole")
    return compact_keyword_query(terms)


def build_switch_query(item: dict[str, Any]) -> str:
    value = str(item.get("value", ""))
    text = item_text(item)
    terms = [value]
    if "3pdt" in value.lower() or "stomp" in text:
        terms.extend(["stomp footswitch", "solder lug"])
    elif "spdt" in value.lower():
        terms.extend(["toggle switch", "on-on", "solder lug"])
    else:
        terms.append("switch")
    return compact_keyword_query(terms)


def build_generic_query(item: dict[str, Any]) -> str:
    value = str(item.get("value", ""))
    text = item_text(item)
    if "transformer" in text:
        return compact_keyword_query([value, "audio transformer", "10k 10k"])
    return compact_keyword_query([value, item.get("category", "")])


def compact_keyword_query(terms: list[Any]) -> str:
    pieces: list[str] = []
    seen: set[str] = set()
    for term in terms:
        sanitized = sanitize_keyword_query(str(term or ""))
        if not sanitized:
            continue
        key = sanitized.lower()
        if key not in seen:
            pieces.append(sanitized)
            seen.add(key)
    return sanitize_keyword_query(" ".join(pieces))


def item_text(item: dict[str, Any]) -> str:
    return item_text_case_sensitive(item).lower()


def item_text_case_sensitive(item: dict[str, Any]) -> str:
    requirements = " ".join(str(requirement) for requirement in item.get("requirements", []))
    return " ".join(str(item.get(field, "")) for field in ("value", "notes")) + " " + requirements


def requirements_text(item: dict[str, Any]) -> str:
    return " ".join(str(requirement) for requirement in item.get("requirements", [])).lower()


def has_requirement(item: dict[str, Any], requirement: str) -> bool:
    return requirement.lower() in item_text(item)


def first_requirement(item: dict[str, Any], options: list[str]) -> str:
    text = item_text_case_sensitive(item)
    for option in options:
        if option in text:
            return option
    return ""


def first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def split_potentiometer_value(value: str) -> tuple[str, str]:
    match = re.match(r"\s*([ABC])\s*(.+?)\s*$", value, flags=re.IGNORECASE)
    if not match:
        return "", normalize_component_value(value)
    taper_code = match.group(1).upper()
    taper = {"A": "audio taper", "B": "linear taper", "C": "reverse audio taper"}.get(taper_code, "")
    return taper, normalize_component_value(match.group(2))


def potentiometer_taper(item: dict[str, Any], fallback: str) -> str:
    text = item_text(item)
    if "reverse audio taper" in text or "reverse log" in text:
        return "reverse audio taper"
    if "audio taper" in text or "log/audio" in text or "log taper" in text:
        return "audio taper"
    if "linear taper" in text:
        return "linear taper"
    return fallback


def normalize_component_value(value: Any) -> str:
    text = str(value).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[Rr]", text)
    if match:
        return f"{match.group(1)} ohm"
    match = re.fullmatch(r"(\d+)[Rr](\d+)", text)
    if match:
        return f"{match.group(1)}.{match.group(2)} ohm"
    match = re.fullmatch(r"(\d+)[Kk](\d+)", text)
    if match:
        return f"{match.group(1)}.{match.group(2)}k"
    match = re.fullmatch(r"(\d+)[Mm](\d+)", text)
    if match:
        return f"{match.group(1)}.{match.group(2)}M"
    return text


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
    body = json.dumps(
        {"SearchByKeywordRequest": {"keyword": query, "records": 50, "startingRecord": 0, "searchOptions": "InStock"}}
    )
    request = urllib.request.Request(
        f"{MOUSER_KEYWORD_URL}?{params}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return execute_search_request(request, max_retries=max_retries, retry_delay=retry_delay, sleeper=sleeper, progress=progress)


def response_parts(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    search_results = response.get("SearchResults")
    if not isinstance(search_results, dict):
        return []
    parts = search_results.get("Parts")
    if not isinstance(parts, list):
        return []
    return parts


def search_keyword_and_manufacturer(
    query: str,
    manufacturer_name: str,
    config: MouserConfig,
    max_retries: int = 2,
    retry_delay: float = 60.0,
    sleeper: Callable[[float], None] = time.sleep,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    params = urllib.parse.urlencode({"apiKey": config.api_key})
    body = json.dumps(
        {
            "SearchByKeywordMfrNameRequest": {
                "keyword": query,
                "manufacturerName": manufacturer_name,
                "records": 50,
                "pageNumber": 1,
                "searchOptions": "InStock",
            }
        }
    )
    request = urllib.request.Request(
        f"{MOUSER_KEYWORD_AND_MANUFACTURER_URL}?{params}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return execute_search_request(request, max_retries=max_retries, retry_delay=retry_delay, sleeper=sleeper, progress=progress)


def execute_search_request(
    request: urllib.request.Request,
    max_retries: int,
    retry_delay: float,
    sleeper: Callable[[float], None],
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
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


def preferred_manufacturer_filters(item: dict[str, Any]) -> list[str]:
    category = item.get("category", "")
    text = item_text(item)
    if category == "resistor":
        return ["YAGEO", "KOA Speer"]
    if category == "capacitor":
        if "film" in text:
            return ["WIMA", "KEMET"]
        if "electrolytic" in text:
            return ["Nichicon", "Panasonic", "Rubycon"]
        if "ceramic" in text or "mlcc" in text or small_capacitor_value(item.get("value", "")):
            return ["KEMET", "Murata Electronics", "TDK"]
    if category == "potentiometer":
        if "trimmer" in text or "3362" in text:
            return ["Bourns"]
        return ["Bourns", "Alpha (Taiwan)"]
    if category in {"semiconductor", "ic"}:
        value = str(item.get("value", ""))
        if re.match(r"^(1N|BAT)", value, flags=re.IGNORECASE):
            return ["onsemi", "Vishay"]
        if re.match(r"^(2N|BC)", value, flags=re.IGNORECASE):
            return ["onsemi", "Central Semiconductor"]
    if category == "jack":
        return ["Switchcraft", "Neutrik"]
    if category == "switch":
        return ["C&K", "NKK Switches"]
    return []


def small_capacitor_value(value: Any) -> bool:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*pF", str(value).strip(), flags=re.IGNORECASE)
    return bool(match and float(match.group(1)) < 1000)


def dedupe_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        key = str(part.get("MouserPartNumber") or part.get("ManufacturerPartNumber") or id(part))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(part)
    return deduped


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
