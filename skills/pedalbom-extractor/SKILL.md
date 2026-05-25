---
name: pedalbom-extractor
description: Extract a normalized bill of materials from DIY guitar pedal or amplifier build documents, validate it with the local pedalbom CLI, and source purchasable parts through Mouser without inventing part numbers.
---

# PedalBOM Extractor

Use this skill when a user provides a DIY pedal/amplifier build document and wants a Mouser-ready BOM.

Public source for the CLI and this skill:

```text
https://github.com/gregbonnette/PedalBOM
```

The skill file is available at:

```text
https://github.com/gregbonnette/PedalBOM/blob/main/skills/pedalbom-extractor/SKILL.md
```

## Core Rule

Never invent manufacturer part numbers, Mouser part numbers, stock status, lifecycle status, or availability. Extract component requirements from the document. Use the `pedalbom` CLI for validation, Mouser candidate search, and export. Use reasoning after candidate search to select the best orderable part for each BOM row.

## CLI Availability

Before validation or sourcing, check whether the CLI is available:

```bash
pedalbom --help
```

If `pedalbom` is not found and this repository is available locally, install it into the current Python environment:

```bash
python -m pip install .
```

If dependency resolution or build isolation fails, make sure build tools are installed, then install the local package without re-resolving dependencies:

```bash
python -m pip install "setuptools>=69" wheel
python -m pip install --no-build-isolation --no-deps .
```

For a persistent user-level CLI outside an activated virtual environment, recommend `pipx`:

```bash
pipx install /path/to/PedalBOM
```

If the repository is not already available locally and network access is allowed, install the CLI from the public repo:

```bash
pipx install git+https://github.com/gregbonnette/PedalBOM.git
```

Do not continue to `pedalbom source` until the user has provided `MOUSER_API_KEY` in the shell environment that runs the CLI. If the repository is not available locally or installation requires network access that is unavailable, ask the user to install the CLI locally and then resume.

`pedalbom source` caches identical search queries during a run, waits between unique Mouser calls, and retries rate-limit responses. If Mouser returns `TooManyRequests`, rerun with a slower delay:

```bash
pedalbom source extracted.bom.json --out sourced.sourced.json --rate-limit-delay 6 --retry-delay 75
```

## Workflow

1. Read the build document and extract a normalized BOM JSON object matching `pedalbom schema`.
2. Preserve evidence for each row in `source_evidence`.
3. Put build-wide constraints in `global_requirements`, such as resistor wattage, capacitor footprint, voltage minimums, pot style, enclosure, or special sourcing notes.
4. Put ambiguities in `issues`; ask the user before sourcing if an issue changes what should be purchased.
5. Run `pedalbom validate extracted.bom.json`.
6. Fix validation errors by editing the JSON, not by changing the schema.
7. Run `pedalbom source extracted.bom.json --out sourced.sourced.json` only after validation succeeds.
8. Review each item's `sourcing.candidates` list and select the best orderable part from those candidates.
9. Populate `manufacturer_part_number`, `mouser_part_number`, and `selection_rationale` for each selected item.
10. Run `pedalbom export sourced.sourced.json --out mouser-bom.csv`.

## Candidate Selection

After `pedalbom source`, do not blindly accept the first candidate. The CLI search score is only a relevance hint. For each item, compare candidates against:

- Exact electrical value and tolerance requirements.
- Package and mounting requirements, especially through-hole versus SMD.
- Power, voltage, current, temperature, polarity, taper, shaft, pinout, footprint, and dielectric requirements.
- Audio suitability for guitar pedals and amplifiers, such as low-noise semiconductors, appropriate capacitor dielectric, film capacitors where specified, resistor wattage, pot taper, and mechanical fit.
- Orderability, in-stock quantity, lifecycle status, lead time, minimum order quantity, multiples, and price breaks.
- User or document preferences, including substitutions, brand notes, enclosure constraints, and global requirements.

Prefer active, in-stock, orderable parts with the shortest practical lead time when they meet the spec. Reject candidates that are obsolete, not recommended for new designs, mismatched footprint/package, under-rated, or only approximately related to the requested part. If no candidate is a confident fit, leave the part numbers blank, add an issue explaining why, and ask the user how to proceed.

Every selected part number must come from `sourcing.candidates` or from explicit source-document evidence. Add `selection_rationale` explaining the fit and any tradeoff, such as "selected 1/4W through-hole metal film 10k resistor, active lifecycle, 3,200 in stock, matches global resistor requirement."

## JSON Shape

Use `pedalbom schema` for the authoritative schema. Minimum shape:

```json
{
  "schema_version": "1.0",
  "project": {
    "name": "Project name",
    "vendor": "Vendor if known",
    "document_version": "Version if known",
    "source_document": "Original filename"
  },
  "global_requirements": [],
  "items": [
    {
      "part_id": "R1",
      "value": "10k",
      "quantity": 1,
      "category": "resistor",
      "notes": "Metal film resistor, 1/4W",
      "requirements": ["through-hole", "1/4W"],
      "source_evidence": "R1 10k Metal film resistor, 1/4W",
      "confidence": 0.99
    }
  ],
  "issues": []
}
```

## Categories

Allowed categories are:

- `resistor`
- `capacitor`
- `potentiometer`
- `semiconductor`
- `ic`
- `socket`
- `switch`
- `jack`
- `hardware`
- `other`

## Extraction Guidance

- Keep `part_id` as the PCB/build document names it: `R1`, `C3`, `GAIN`, `IC1-S`, `BYPASS`.
- Preserve grouped designators only when the document groups them and they share the same requirements.
- Use `quantity` from the document when present; otherwise count grouped designators.
- Treat substitutions and optional mods as notes or issues unless the user chooses them.
- For duplicate or conflicting designators, add an `issues` entry.
- Manufacturer and Mouser part numbers must remain absent or blank unless explicitly printed in the source document or selected from `pedalbom source` candidates.

## Commands

```bash
pedalbom schema
pedalbom validate extracted.bom.json
pedalbom inspect extracted.bom.json
pedalbom source extracted.bom.json --out sourced.sourced.json --rate-limit-delay 6 --retry-delay 75
# Review sourced.sourced.json and choose selected parts from sourcing.candidates.
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

If the document is text-extractable and the user wants a first draft, `pedalbom extract build.pdf --out extracted.bom.json` can be used as a fallback. Review and correct the result before sourcing.
