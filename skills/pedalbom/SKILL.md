---
name: pedalbom
description: Extract a normalized bill of materials from DIY guitar pedal or amplifier build documents, validate it with the local pedalbom CLI, and source purchasable parts through Mouser without inventing part numbers.
---

# PedalBOM

Use this skill when a user provides a DIY pedal/amplifier build document and wants a Mouser-ready BOM.

Public source for the CLI and this skill:

```text
https://github.com/gregbonnette/PedalBOM
```

The skill file is available at:

```text
https://github.com/gregbonnette/PedalBOM/blob/main/skills/pedalbom/SKILL.md
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

Do not continue to `pedalbom source` until the user has provided `MOUSER_API_KEY` in the shell environment that runs the CLI. Check local setup with:

```bash
pedalbom doctor
```

Mouser API access can be restricted by source IP address. If running inside Claude.ai, a hosted Claude environment, or any environment that is not the user's local machine/network, do not call `pedalbom source` there. Instead, prepare and validate `extracted.bom.json`, then ask the user to run the sourcing command from their local terminal and provide `sourced.sourced.json` back to continue candidate selection.

If the repository is not available locally or installation requires network access that is unavailable, ask the user to install the CLI locally and then resume.

`pedalbom source` caches identical search queries during a run, waits between unique Mouser calls, and retries rate-limit responses. If Mouser returns `TooManyRequests`, rerun with a slower delay:

```bash
pedalbom source extracted.bom.json --out sourced.sourced.json --rate-limit-delay 6 --retry-delay 75
```

CLI progress messages are expected and useful during long sourcing runs. Only add `--quiet` if the user explicitly wants less console output.

If Mouser returns `InvalidCharacters`, update/reinstall the CLI and rerun sourcing. The CLI sanitizes common electronics symbols before search and reports the failing BOM item plus Mouser query when the API still rejects a keyword.

## Workflow

1. Read the build document and extract a normalized BOM JSON object matching `pedalbom schema`.
2. Preserve evidence for each row in `source_evidence`.
3. Put build-wide constraints in `global_requirements`, such as resistor wattage, capacitor footprint, voltage minimums, pot style, enclosure, or special sourcing notes.
4. Put ambiguities in `issues`; ask the user before sourcing if an issue changes what should be purchased.
5. Run `pedalbom validate extracted.bom.json`.
6. Fix validation errors by editing the JSON, not by changing the schema.
7. Run `pedalbom doctor` in the same local shell that will run sourcing.
8. Run `pedalbom source extracted.bom.json --out sourced.sourced.json` only after validation succeeds and only from the user's local allowed IP environment.
9. If local execution is not available to the assistant, give the user the exact `pedalbom source` command to run locally and wait for `sourced.sourced.json`.
10. Review each item's `sourcing.candidates` list and select the best orderable part from those candidates.
11. Populate `manufacturer_part_number`, `mouser_part_number`, and `selection_rationale` for each selected item.
12. Run `pedalbom export sourced.sourced.json --out mouser-bom.csv`.

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

The Mouser search query should describe the core product, not the whole source note. Keep search terms focused on exact value or part number, product type, package/footprint, and critical guitar-pedal fit semantics. Never include PCB designators such as `R2`, `C3`, `Q1`, grouped designators, or `source_evidence` text in Mouser search keywords. Exclude prose such as "adjust to taste", original-circuit commentary, unselected substitutions, and build caveats unless they directly change the part to purchase.

## Pedal Component Knowledge

Use this component knowledge to improve Mouser search terms and candidate selection. Do not use it to choose an online vendor; default to Mouser for API sourcing. Only if Mouser cannot provide a suitable part should a later manual browser pass check Love My Switches or Small Bear. Any non-Mouser sourced row in the final CSV must set `supplier` and include a product-page hyperlink in `product_url`.

- Resistors: prefer 1/4W metal film resistors for pedal builds. On Mouser, prefer reputable commodity lines such as Yageo or KOA Speer. Avoid carbon film unless explicitly required. Avoid flimsy low-quality metal film parts with thin leads.
- Film capacitors: for common signal-path film values, prefer box film parts with the requested lead spacing, especially WIMA MKS2 for about 10nF through 2.2uF when the footprint fits. For small pF/nF precision parts, consider Kemet PHE426-style polystyrene when the BOM or circuit calls for that behavior.
- Ceramic and MLCC capacitors: for values below 1nF / 1000pF, prefer MLCC parts with C0G/NP0 dielectric. Avoid Z5U, X5R, and X7R for audio signal-path substitutions when C0G/NP0 is practical; they are Class 2 dielectrics and can be nonlinear. Do not select large-value MLCCs such as 1uF for audio path unless the BOM explicitly requires them.
- Electrolytic capacitors: for values above practical film sizes, prefer high-quality radial electrolytics from Nichicon, Panasonic, Rubycon, or Lelon, matching voltage rating, diameter, height, and lead pitch. Avoid old-stock electrolytics and avoid low-quality electrolytics when a reputable Mouser part is available.
- Tantalum capacitors: only select tantalum if the BOM explicitly calls for it or the circuit/application clearly expects it. Otherwise prefer film or electrolytic according to value and footprint.
- Potentiometers: for board-mounted pedal pots, prefer Alpha-style 16mm right-angle PCB mount where footprint allows; 9mm pots are appropriate for tight layouts. Match resistance, taper, shaft type/diameter, bushing, orientation, and PCB footprint. Respect A/audio, B/linear, C/reverse audio, and special W taper requirements.
- Diodes: for standard silicon switching, rectifier, Schottky, BAT41/BAT46, and LEDs, match exact part number/package when given. For clipping diodes, do not substitute different diode families or forward-voltage behavior unless the BOM or user allows it. For LEDs, match size, lens style, color, brightness expectations, and leaded package.
- Transistors and JFETs: for in-production silicon transistors, prefer authorized-distribution Mouser parts and match polarity, package, pinout, gain grade, and noise/application notes. Avoid suspiciously cheap or unauthenticated substitutes. For germanium or obsolete transistors, flag uncertainty and ask before substituting; audited parts from specialist suppliers may be needed in a manual fallback pass.
- ICs: for in-production ICs, prefer genuine authorized-distribution parts. Match exact suffix/package, through-hole DIP versus SMD, voltage range, and audio/noise requirements. Be careful with obsolete ICs and known-problem parts such as noisy/factory-second PT2399 sources; flag when Mouser availability is poor or substitutions are risky.
- Enclosures and knobs: these are often better found outside Mouser, but keep Mouser as the default sourcing attempt. If missing from Mouser, a browser fallback to Love My Switches or Small Bear is acceptable, with product-page hyperlinks in the final CSV for non-Mouser rows.
- 1/4 inch jacks: prefer Switchcraft #111 mono and #112 stereo enclosed jacks, or Neutrik NMJ series when isolation or switching behavior is needed. Avoid unbranded/flimsy jacks for final builds.
- DC jacks: prefer reliable Kobiconn-style switched DC jacks for pedal builds, including Mouser part 163-4302-E where appropriate. For tight builds, note that smaller non-switched jacks may be required, but do not use a non-switched jack where battery switching is needed.
- Stomp switches and toggles: match pole/throw and mounting style. For 3PDT stomp switches and SPDT/DPDT/3PDT toggles, prefer reliable Taiway/Gorva/Love My Switches-style parts in a manual fallback if Mouser candidates are unsuitable. For toggles, short bat handles are often preferred for pedal ergonomics.
- Wire: if wire is included, prefer flexible pre-bonded/hookup wire suitable for pedal wiring. This may require manual fallback sourcing if Mouser candidates are not appropriate.

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
pedalbom doctor
pedalbom source extracted.bom.json --out sourced.sourced.json --rate-limit-delay 6 --retry-delay 75
# Review sourced.sourced.json and choose selected parts from sourcing.candidates.
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

If the document is text-extractable and the user wants a first draft, `pedalbom extract build.pdf --out extracted.bom.json` can be used as a fallback. Review and correct the result before sourcing.
