# PedalBOM

PedalBOM is a local-first sourcing utility for DIY guitar pedal and amplifier build documents.

The recommended architecture is agent-assisted:

- An LLM skill reads arbitrary build instructions and extracts a normalized BOM JSON file.
- The `pedalbom` CLI validates that JSON, calls Mouser with the user's own API key, and exports a CSV.
- Manufacturer and Mouser part numbers are never invented by the LLM. They must come from the source document or the Mouser API.

## Install

From this repository:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Or, if you prefer `pipx`:

```bash
pipx install .
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
```

## Claude Setup

### Claude.ai or Claude Desktop

Claude supports custom Skills as uploadable skill folders. Create a ZIP that contains the skill directory:

```text
pedalbom-extractor/
  SKILL.md
```

Use the file at:

```text
skills/pedalbom-extractor/SKILL.md
```

Then, in Claude:

1. Enable Skills and code execution if your plan/workspace requires it.
2. Add or upload the `pedalbom-extractor` skill folder.
3. Start a chat, upload the build document PDF, and ask:

```text
Use the PedalBOM skill to create a Mouser BOM from this build document.
```

Claude should extract `extracted.bom.json`, validate it with the CLI, ask about any ambiguous parts, run Mouser sourcing with your local API key, and export `mouser-bom.csv`.

### Claude Code

For a personal Claude Code skill:

```bash
mkdir -p ~/.claude/skills/pedalbom-extractor
cp skills/pedalbom-extractor/SKILL.md ~/.claude/skills/pedalbom-extractor/SKILL.md
```

For a project-local skill, copy it into:

```text
.claude/skills/pedalbom-extractor/SKILL.md
```

Then run Claude Code from a shell where `pedalbom` and `MOUSER_API_KEY` are available.

## ChatGPT Setup

ChatGPT does not use Claude-style `SKILL.md` files as native executable skills. Use the same instructions as a Project or custom GPT instruction set, then run the CLI either manually or through an agent environment that has terminal access.

### ChatGPT Project

1. Create a ChatGPT Project for PedalBOM work.
2. Add the contents of `skills/pedalbom-extractor/SKILL.md` to the Project instructions.
3. Upload `src/pedalbom/schema/bom.schema.json` as a reference file.
4. Upload a build document PDF and ask:

```text
Using the PedalBOM instructions and schema, extract this build document to PedalBOM JSON. Do not invent manufacturer or Mouser part numbers.
```

If ChatGPT cannot run local commands in your environment, have it produce `extracted.bom.json`, then run:

```bash
pedalbom validate extracted.bom.json
pedalbom inspect extracted.bom.json
pedalbom source extracted.bom.json --out sourced.sourced.json
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

### Custom GPT

1. Create a custom GPT.
2. Paste the contents of `skills/pedalbom-extractor/SKILL.md` into the GPT instructions.
3. Add `src/pedalbom/schema/bom.schema.json` as knowledge.
4. Enable file upload/analysis capabilities.
5. Use the GPT to extract validated JSON, then run the CLI locally for validation, Mouser sourcing, and CSV export.

If you are using a ChatGPT/Codex-style local agent with terminal access, point it at this repository and ask it to use `skills/pedalbom-extractor/SKILL.md`; it can run the same CLI commands directly.

## Agent Workflow

Whichever assistant you use, the target workflow is:

1. The LLM reads the PDF and writes `extracted.bom.json`.
2. The CLI validates the JSON.
3. The user resolves any ambiguity.
4. The CLI calls Mouser using the user's API key.
5. The CLI exports the final CSV.

The central prompt is:

```text
Use the PedalBOM skill to create a Mouser BOM from this build document.
```

The assistant or user should then run:

```bash
pedalbom validate extracted.bom.json
pedalbom inspect extracted.bom.json
pedalbom source extracted.bom.json --out sourced.sourced.json
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

## CLI Commands

```bash
pedalbom schema
pedalbom validate extracted.bom.json
pedalbom inspect extracted.bom.json
pedalbom source extracted.bom.json --out sourced.sourced.json
pedalbom export sourced.sourced.json --out mouser-bom.csv
```

There is also a fallback parser for text-extractable PDFs:

```bash
pedalbom extract build.pdf --out extracted.bom.json
```

Treat fallback extraction as a draft. Review it before sourcing.
