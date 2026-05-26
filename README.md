# PedalBOM

PedalBOM is a local-first sourcing utility for DIY guitar pedal and amplifier build documents.

The recommended architecture is agent-assisted:

- An LLM skill reads arbitrary build instructions and extracts a normalized BOM JSON file.
- The `pedalbom` CLI validates that JSON and calls Mouser from the user's local environment with the user's own API key to collect orderable candidate parts.
- The LLM reviews the Mouser candidates for each row, selects the best available fit, records the selection rationale, and then the CLI exports a CSV.
- Manufacturer and Mouser part numbers are never invented by the LLM. They must come from the source document or the Mouser API.

## Install

Public repository:

```text
https://github.com/gregbonnette/PedalBOM
```

From a local checkout of this repository:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Or, if you prefer `pipx`:

```bash
pipx install .
```

Or install the CLI directly from GitHub:

```bash
pipx install git+https://github.com/gregbonnette/PedalBOM.git
```

Set your Mouser Search API key in the shell that will run `pedalbom`:

```bash
export MOUSER_API_KEY="your-key"
```

For Windows PowerShell:

```powershell
$env:MOUSER_API_KEY = "your-key"
```

Verify the CLI:

```bash
pedalbom --help
pedalbom schema
pedalbom doctor
```

## Claude Setup

### Claude.ai or Claude Desktop

Claude supports custom Skills as uploadable skill folders. Create a ZIP that contains the skill directory:

```text
pedalbom/
  SKILL.md
```

Use the file at:

```text
skills/pedalbom/SKILL.md
```

The public source for both the skill and CLI is:

```text
https://github.com/gregbonnette/PedalBOM
```

The skill file lives at:

```text
https://github.com/gregbonnette/PedalBOM/blob/main/skills/pedalbom/SKILL.md
```

Then, in Claude:

1. Enable Skills and code execution if your plan/workspace requires it.
2. Add or upload the `pedalbom` skill folder.
3. Start a chat, upload the build document PDF, and ask:

```text
Use the PedalBOM skill to create a Mouser BOM from this build document.
```

Claude should extract `extracted.bom.json`, validate it with the CLI, ask about any ambiguous parts, run Mouser sourcing from your local environment with your local API key, select the best orderable candidates from the search results, and export `mouser-bom.csv`.

Mouser API access can be restricted by source IP address. If Claude is running in a hosted environment that is not your local machine/network, have Claude prepare `extracted.bom.json`, then run the `pedalbom source ...` command yourself in a local terminal and provide `sourced.sourced.json` back to Claude for candidate selection.

### Claude Code

For a personal Claude Code skill:

```bash
mkdir -p ~/.claude/skills/pedalbom
cp skills/pedalbom/SKILL.md ~/.claude/skills/pedalbom/SKILL.md
```

For a project-local skill, copy it into:

```text
.claude/skills/pedalbom/SKILL.md
```

Then run Claude Code from a local shell where `pedalbom`, `MOUSER_API_KEY`, and your Mouser-allowed network/IP are available.

## ChatGPT Setup

ChatGPT does not use Claude-style `SKILL.md` files as native executable skills. Use the same instructions as a Project or custom GPT instruction set, then run the CLI either manually or through an agent environment that has terminal access.

### ChatGPT Project

1. Create a ChatGPT Project for PedalBOM work.
2. Add the contents of `skills/pedalbom/SKILL.md` to the Project instructions.
3. Upload `src/pedalbom/schema/bom.schema.json` as a reference file.
4. Upload a build document PDF and ask:

```text
Using the PedalBOM instructions and schema, extract this build document to PedalBOM JSON. Do not invent manufacturer or Mouser part numbers.
```

If ChatGPT cannot run local commands in your environment, have it produce `extracted.bom.json`, then run:

```bash
pedalbom validate extracted.bom.json
pedalbom inspect extracted.bom.json
pedalbom doctor
pedalbom source extracted.bom.json --out sourced.sourced.json --rate-limit-delay 6 --retry-delay 75
# Review sourced.sourced.json and choose selected parts from sourcing.candidates.
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

### Custom GPT

1. Create a custom GPT.
2. Paste the contents of `skills/pedalbom/SKILL.md` into the GPT instructions.
3. Add `src/pedalbom/schema/bom.schema.json` as knowledge.
4. Enable file upload/analysis capabilities.
5. Use the GPT to extract validated JSON, then run the CLI locally for validation, Mouser candidate search, candidate selection, and CSV export.

If you are using a ChatGPT/Codex-style local agent with terminal access, point it at this repository and ask it to use `skills/pedalbom/SKILL.md`; it can run the same CLI commands directly.

## Agent Workflow

Whichever assistant you use, the target workflow is:

1. The LLM reads the PDF and writes `extracted.bom.json`.
2. The CLI validates the JSON.
3. The user resolves any ambiguity.
4. The CLI calls Mouser from the user's local allowed IP environment and writes candidate search results.
5. The LLM reviews those candidates and selects the best orderable part for each row.
6. The CLI exports the final CSV.

The central prompt is:

```text
Use the PedalBOM skill to create a Mouser BOM from this build document.
```

The assistant or user should then run:

```bash
pedalbom validate extracted.bom.json
pedalbom inspect extracted.bom.json
pedalbom doctor
pedalbom source extracted.bom.json --out sourced.sourced.json --rate-limit-delay 6 --retry-delay 75
# Have the assistant review sourced.sourced.json, choose parts from each
# item's sourcing.candidates list, and populate manufacturer_part_number,
# mouser_part_number, and selection_rationale.
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

## CLI Commands

```bash
pedalbom schema
pedalbom validate extracted.bom.json
pedalbom inspect extracted.bom.json
pedalbom doctor
pedalbom source extracted.bom.json --out sourced.sourced.json --rate-limit-delay 6 --retry-delay 75
# Review sourced.sourced.json and choose selected parts from sourcing.candidates.
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

`pedalbom source` caches identical search queries during a run. Use `--rate-limit-delay` to slow unique Mouser calls and `--retry-delay` to wait longer after a `TooManyRequests` response.

Long-running commands print progress messages to stderr. Add `--quiet` to `extract`, `validate`, `source`, or `export` to suppress progress output.

If Mouser returns `InvalidCharacters`, update/reinstall the CLI and rerun sourcing. The CLI sanitizes common electronics symbols before search and reports the failing BOM item plus Mouser query when the API still rejects a keyword.

Mouser searches are intentionally compact and in-stock-only: the CLI focuses each keyword on the core value or part number, product type, package/footprint, and critical guitar-pedal fit terms instead of sending the full BOM note text. PCB designators such as `R2`, `C3`, grouped designators, and `source_evidence` text are not included in Mouser search keywords. Where preferred manufacturers are known, the CLI cascades through Mouser V2 manufacturer-filtered searches first and only falls back to generic keyword search if those manufacturer searches return no candidates.

There is also a fallback parser for text-extractable PDFs:

```bash
pedalbom extract build.pdf --out extracted.bom.json
```

Treat fallback extraction as a draft. Review it before sourcing.
