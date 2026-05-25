from __future__ import annotations

import re
from pathlib import Path

from .models import BomItem, BuildDocument
from .pdf_extract import extract_pdf_text

BOM_SECTIONS = {
    "Resistors": "resistors",
    "Capacitors": "capacitors",
    "Potentiometers": "potentiometers",
    "Semiconductors": "semiconductors",
    "Other": "other",
}

SECTION_ENDINGS = {
    "Sourcing Parts",
    "Transformer information",
    "Drill Template",
    "Wiring",
    "Part Substitution",
    "Circuit Observations",
    "Schematic",
}

DESIGNATOR_SECTIONS = {
    "resistors": ("R",),
    "capacitors": ("C",),
    "semiconductors": ("D", "Q", "IC", "U", "Z", "REG"),
}

POT_VALUE_RE = re.compile(r"^[ABCW]?\d+(?:R|K|M)?$", re.IGNORECASE)
COUNT_RE = re.compile(r"^\d+$")
DESIGNATOR_RE = re.compile(r"^[A-Z]+[0-9]+$", re.IGNORECASE)
GENERIC_PART_RE = re.compile(
    r"^(?P<part_id>"
    r"[A-Z]+[0-9]+(?:-S)?|"
    r"LEDR|REG|"
    r"SPEED\s+[AB]|"
    r"CH/VIBE|CANCEL|INPUT|GAIN|OFFSET|PHASE|INTENSITY|VOLUME|"
    r"LED|IN|OUT|DC|BYPASS|SPEED|ENCLOSURE"
    r")\s+(?P<rest>.+)$",
    flags=re.IGNORECASE,
)

TYPE_MARKERS = [
    "Metal film resistor",
    "Film capacitor",
    "Electrolytic capacitor",
    "MLCC capacitor",
    "Schottky diode",
    "Fast-switching diode",
    "Zener diode",
    "Darlington BJT transistor",
    "BJT transistor",
    "Regulator",
    "Charge pump",
    "IC socket",
    "Incandescent lamp",
    "LDR,",
    "16mm",
    "Toggle switch",
    "T oggle switch",
    "Slide switch",
    "Trimmer",
    "LED,",
    '1/4" phone jack',
    "DC jack",
    "Stomp switch",
    "Enclosure",
]


def parse_pdf(path: str | Path) -> BuildDocument:
    text = extract_pdf_text(path)
    return parse_text(text, source_name=Path(path).name)


def parse_text(text: str, source_name: str = "document") -> BuildDocument:
    global_notes = extract_global_notes(text)
    items: list[BomItem] = []
    warnings: list[str] = []
    section_warnings: list[str] = []
    for title, section_key in BOM_SECTIONS.items():
        section_lines = extract_section_lines(text, title)
        if not section_lines:
            section_warnings.append(f"Could not find BOM section: {title}")
            continue
        items.extend(parse_section(section_key, section_lines))

    if not items:
        items = parse_generic_parts_list(text)
        if not items:
            warnings.extend(section_warnings)

    add_cross_item_warnings(items)
    return BuildDocument(
        source_name=source_name,
        text=text,
        items=items,
        warnings=warnings,
        global_notes=global_notes,
    )


def extract_global_notes(text: str) -> list[str]:
    notes: list[str] = []
    patterns = [
        r"footprints on the PCB support (?P<note>.+?resistors)\.",
        r"powered by (?P<note>a regulated.+?minimum of 100mA)",
    ]
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            notes.append(clean_text(match.group("note")))
    return notes


def extract_section_lines(text: str, title: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    start = None
    for index, line in enumerate(lines):
        if line == title:
            start = index + 1
            break
    if start is None:
        return []

    collected: list[str] = []
    for line in lines[start:]:
        if not line:
            continue
        if line in BOM_SECTIONS and line != title:
            break
        if line in SECTION_ENDINGS:
            break
        if line.startswith("--- PAGE"):
            continue
        collected.append(line)
    return collected


def parse_section(section: str, lines: list[str]) -> list[BomItem]:
    items: list[BomItem] = []
    current: BomItem | None = None
    pending = ""

    for raw_line in lines:
        line = clean_text(raw_line)
        if not line or is_header_line(line):
            continue

        candidate = f"{pending} {line}".strip() if pending else line
        parsed = parse_row(section, candidate)
        if parsed:
            if current:
                items.append(current)
            current = parsed
            pending = ""
            continue

        if pending:
            pending = candidate
            parsed = parse_row(section, pending)
            if parsed:
                if current:
                    items.append(current)
                current = parsed
                pending = ""
            continue

        if begins_new_unfinished_row(section, line):
            pending = candidate
            continue

        if current:
            current.notes = append_note(current.notes, line)

    if pending and current:
        current.notes = append_note(current.notes, pending)
    if current:
        items.append(current)
    return items


def parse_generic_parts_list(text: str) -> list[BomItem]:
    items: list[BomItem] = []
    in_parts_table = False
    for raw_line in text.splitlines():
        line = clean_text(raw_line)
        if not line or line.startswith("--- PAGE"):
            continue
        if is_repeated_page_header(line):
            continue
        if line == "BUILD NOTES":
            break
        if line == "PART VALUE TYPE NOTES":
            in_parts_table = True
            continue
        if not in_parts_table:
            continue
        if line in {"PARTS LIST, CONT.", "PARTS LIST"}:
            continue

        item = parse_generic_parts_row(line)
        if item:
            items.append(item)
        elif items:
            items[-1].notes = append_note(items[-1].notes, line)
    return items


def parse_generic_parts_row(line: str) -> BomItem | None:
    match = GENERIC_PART_RE.match(line)
    if not match:
        return None
    part_id = clean_text(match.group("part_id")).upper()
    rest = clean_text(match.group("rest"))
    value, notes = split_value_type_notes(rest)
    section = classify_generic_part(part_id, value, notes)
    return BomItem(section=section, part_id=part_id, value=value, quantity=1, notes=notes)


def split_value_type_notes(rest: str) -> tuple[str, str]:
    matches: list[tuple[int, str]] = []
    lower_rest = rest.lower()
    for marker in TYPE_MARKERS:
        index = lower_rest.find(marker.lower())
        if index > 0:
            matches.append((index, marker))
    if matches:
        index, _marker = min(matches, key=lambda item: item[0])
        return rest[:index].strip(), normalize_extracted_text(rest[index:].strip())

    tokens = rest.split()
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], " ".join(tokens[1:])


def normalize_extracted_text(value: str) -> str:
    normalized = clean_text(value.replace("T oggle", "Toggle"))
    normalized = re.sub(r"^trimmer\s+Trimmer", "Trimmer", normalized, flags=re.IGNORECASE)
    return normalized


def classify_generic_part(part_id: str, value: str, notes: str) -> str:
    if part_id in {"CH/VIBE", "CANCEL", "INPUT", "IN", "OUT", "DC", "BYPASS", "SPEED", "ENCLOSURE"}:
        return "other"
    if part_id in {"REG", "LED"}:
        return "semiconductors"
    if part_id.startswith("R") or part_id == "LEDR":
        return "resistors"
    if part_id.startswith("C"):
        return "capacitors"
    if part_id.startswith(("D", "Q", "Z", "REG", "IC", "LDR")):
        return "semiconductors"
    if part_id.startswith("L") and "lamp" in notes.lower():
        return "semiconductors"
    if "pot" in notes.lower() or "trimmer" in notes.lower():
        return "potentiometers"
    return "other"


def is_repeated_page_header(line: str) -> bool:
    return (
        line.isdigit()
        or line == "STRAYLIGHT CHORUS/VIBE"
        or re.match(r"^[A-Z][A-Z0-9 /\-]+ \d+$", line) is not None
    )


def parse_row(section: str, line: str) -> BomItem | None:
    if section in DESIGNATOR_SECTIONS:
        return parse_designator_row(section, line)
    if section == "potentiometers":
        return parse_pot_row(line)
    if section == "other":
        return parse_other_row(line)
    return None


def parse_designator_row(section: str, line: str) -> BomItem | None:
    split = split_designator_prefix(section, line)
    if not split:
        return None
    part_id, rest = split
    value_split = split_value_count_notes(rest)
    if not value_split:
        return None
    value, quantity, notes = value_split
    item = BomItem(section=section, part_id=part_id, value=value, quantity=quantity, notes=notes)
    validate_designator_count(item)
    return item


def split_designator_prefix(section: str, line: str) -> tuple[str, str] | None:
    prefixes = DESIGNATOR_SECTIONS[section]
    tokens = line.split()
    part_tokens: list[str] = []
    rest_index = 0
    for index, token in enumerate(tokens):
        normalized = token.strip(",").upper()
        if DESIGNATOR_RE.match(normalized) and normalized.startswith(prefixes):
            part_tokens.append(token)
            rest_index = index + 1
            continue
        break
    if not part_tokens or rest_index >= len(tokens):
        return None
    return clean_designators(" ".join(part_tokens)), " ".join(tokens[rest_index:])


def parse_pot_row(line: str) -> BomItem | None:
    tokens = line.split()
    for index, token in enumerate(tokens):
        if POT_VALUE_RE.match(token) and index + 1 < len(tokens) and COUNT_RE.match(tokens[index + 1]):
            part_id = " ".join(tokens[:index])
            value = token
            quantity = int(tokens[index + 1])
            notes = " ".join(tokens[index + 2 :])
            return BomItem("potentiometers", part_id, value, quantity, notes)
    return None


def parse_other_row(line: str) -> BomItem | None:
    split = split_value_count_notes(line)
    if not split:
        return None
    left, quantity, notes = split
    words = left.split()
    if len(words) < 2:
        return None
    part_id = " ".join(words[:-1])
    value = words[-1]
    return BomItem("other", part_id, value, quantity, notes)


def split_value_count_notes(text: str) -> tuple[str, int, str] | None:
    tokens = text.split()
    for index, token in enumerate(tokens):
        if COUNT_RE.match(token) and is_plausible_quantity_token(token):
            value = " ".join(tokens[:index]).strip()
            notes = " ".join(tokens[index + 1 :]).strip()
            if value:
                return value, int(token), notes
    return None


def is_plausible_quantity_token(token: str) -> bool:
    quantity = int(token)
    return 1 <= quantity <= 99


def begins_new_unfinished_row(section: str, line: str) -> bool:
    if section in DESIGNATOR_SECTIONS:
        first = line.split()[0].strip(",").upper() if line.split() else ""
        return DESIGNATOR_RE.match(first) is not None and first.startswith(DESIGNATOR_SECTIONS[section])
    if section in {"potentiometers", "other"}:
        return bool(line and line[0].isupper())
    return False


def clean_designators(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace(" ,", ",")).strip().rstrip(",")


def designators_match_section(section: str, part_id: str) -> bool:
    prefixes = DESIGNATOR_SECTIONS[section]
    designators = expand_designator_text(part_id)
    return bool(designators) and all(designator.upper().startswith(prefixes) for designator in designators)


def expand_designator_text(part_id: str) -> list[str]:
    return [
        token.strip().upper()
        for token in re.split(r"[\s,]+", part_id)
        if DESIGNATOR_RE.match(token.strip())
    ]


def validate_designator_count(item: BomItem) -> None:
    designators = expand_designator_text(item.part_id)
    if designators and len(designators) != item.quantity:
        item.warnings.append(
            f"Designator count ({len(designators)}) does not match quantity ({item.quantity})"
        )


def add_cross_item_warnings(items: list[BomItem]) -> None:
    seen: dict[str, BomItem] = {}
    for item in items:
        for designator in expand_designator_text(item.part_id):
            previous = seen.get(designator)
            if previous:
                message = f"{designator} also appears in {previous.section}: {previous.value}"
                item.warnings.append(message)
                previous.warnings.append(f"{designator} also appears in {item.section}: {item.value}")
            else:
                seen[designator] = item


def append_note(existing: str, addition: str) -> str:
    if not existing:
        return addition
    return f"{existing} {addition}"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("“", '"').replace("”", '"')).strip()


def is_header_line(line: str) -> bool:
    normalized = line.lower()
    return normalized in {
        "part id value count total note",
        "bill of materials",
    }
