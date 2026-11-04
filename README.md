# SDS extraction pipeline

Extracts **trade name**, **revision date** and **hazard statements** from Safety Data Sheet (SDS) PDFs into structured data (JSON and CSV) for import into a master data system.

## Results

| document | trade name | revision date | hazard statements | status |
|---|---|---|---|---|
| assSDS-120636860 | Super Silicone Kitchen | 15/07/2026 | EUH208, EUH210 | ok |
| assSDS-123006278 | Kroon-Oil Fuel Optimix 2T | 21/07/2026 | H224, H304, H315, H336, H411 | ok |
| assSDS-128374293 | BISON KIT TRANSPARANT | 20/04/2026 | H225, H319, H336, EUH066 | ok |

All values match the hand-checked answers in [`data/gold.json`](data/gold.json) (rules-only run: 3/3 names, 3/3 dates, 11/11 hazard codes; see [evaluation](runs/20261104-073638_rules/evaluation.md)). LLM run: _pending_.

## Quick start

Requires Python 3.10+. No network, model or API key is needed for the default run.

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m sds_extractor          # reads data/input, writes runs/<timestamp>_rules/
.venv/bin/python -m pytest -q              # 17 tests
```

```powershell
# Windows (no venv activation needed)
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m sds_extractor
.venv\Scripts\python -m pytest -q
```

Optional LLM mode (local [Ollama](https://ollama.com)): `ollama pull qwen2.5:7b`, then add `--llm` (and `--model <tag>` for another model). If Ollama is not running, the pipeline logs why and continues with rules only.

Evaluate any run: `python evaluate.py runs/<run_id>/results.json`.

**What the code touches:** it reads the PDFs in the input folder and writes a new folder under `runs/`. The default run makes no network calls; `--llm` only calls the Ollama server on `localhost`.

## Success criteria

1. Every field matches the hand-checked value for the three samples.
2. No hazard code from outside section 2.2 (the ingredient list in section 3 also contains H-codes).
3. No value is accepted silently without a check: LLM values must appear in the source text, and disagreements are flagged.
4. Runs on any OS without a model or network access (paths via `pathlib`, all files UTF-8; tested on Linux with Python 3.10 and 3.13).

## How it works

```
PDF → text (pypdf) → find sections 1.1 and 2.2 by number → extract → validate / reconcile → JSON, CSV, log
```

Sections are located by their number ("2.2"), not their heading, because SDSs follow the REACH 16-section structure and the numbers are the same in every language.

| field | method | why |
|---|---|---|
| hazard statements | regex `H`/`EUH` + 3 digits, **section 2.2 only** | The format is fully specified, so a regex is exact. An LLM would only add the risk of invented codes. |
| trade name | label rule (`Handelsnaam`, `Trade name`, …) + optional LLM | Labels and layouts vary by supplier and language; the LLM covers labels the rules don't know. |
| revision date | label rule + optional LLM; code converts to dd/mm/yyyy | Picking the revision date over the print/issue date needs interpretation; formatting does not. |

**Guardrails for the LLM** (`sds_extractor/llm.py`, `pipeline.py`): the model returns a Pydantic-validated JSON object; a value is accepted only if it appears verbatim in the text the model was given (and, for dates, is a real date). Then rule and LLM are reconciled:

| rule | LLM | result |
|---|---|---|
| value | same value | accepted, source `rule+llm` |
| value | different value | rule value kept, status `needs_review` |
| value | none / rejected | rule value |
| none | grounded value | LLM value, source `llm` |
| none | none | empty, status `needs_review` |

Status: `ok`, `needs_review` (a person should check) or `error` (e.g. section 2.2 not found). `hazard_statements` is `""` when section 2.2 was found and lists no codes, and `null` when it could not be read: "no hazards" and "could not read" are different answers.

## Decisions and assumptions

- **PDF library: pypdf.** Tested pypdf, PyMuPDF and pdfplumber on all 9 values. pdfplumber garbles the trade names where two texts are printed on top of each other; pypdf and PyMuPDF got 9/9. pypdf is pure Python and permissively licensed (PyMuPDF is AGPL).
- **Trade name** = the text on the label's line only. In two documents an internal article code (`GRF SILICONE S-200 TR CQ 300ML*12 L001`) is printed with the name; it is treated as a product identifier and excluded, like the UFI.
- **Revision date** = only a date with a revision label. Print date, first-issue date and "replaces version of" dates are ignored. Dates are read day-first (European documents). If no revision date is found the field stays empty; the print date is never used as a substitute.
- **Hazard statements** = every H/EUH code printed in section 2.2. In two documents some EUH codes are listed under "Aanvullende gegevens" (supplemental information) rather than under "Gevarenaanduidingen". The definition explicitly includes the EUH format, so they are included. A stricter reading would give:

  | document | included (this pipeline) | strict reading |
  |---|---|---|
  | assSDS-120636860 | EUH208, EUH210 | _(none: "Niet van toepassing")_ |
  | assSDS-128374293 | H225, H319, H336, EUH066 | H225, H319, H336 |

- **Code format** follows the brief (`H` + 3 digits): a suffix such as `H360FD` would be reported as `H360`. None occur in section 2.2 of the samples.
- **document_id** is the file name; it looks like an internal asset ID and would be the key to link records to products later.

## Findings from the documents

- Searching the whole document instead of section 2.2 gives 12 codes for assSDS-120636860 instead of 2, adds EUH066 to assSDS-123006278 (it belongs to an ingredient), and adds H317, H361, H400 and H410 to assSDS-128374293.
- assSDS-128374293 prints `Afdrukdatum: 08.07.2026 herzien op: 20.04.2026`: the print date is the obvious wrong answer. A test checks that an LLM picking it is flagged.
- Comparing PDF libraries exposed a bug in the first hazard-code regex: pypdf returns `H225Licht…` without a space, and a word-boundary pattern silently missed those codes. The pattern and a regression test were updated.

## Known limitations

- Three samples in two layouts, all Dutch: rules for other languages and layouts are untested.
- Scanned PDFs (no text layer) are reported as errors; there is no OCR.
- Sections are found by numbered headings; documents without them fail with status `error`.
- A trade name spanning two lines is cut to the first line; only an LLM disagreement would flag it.
- Only numeric dates are recognised (`15.07.2026`, `21-7-2026`, `2026-04-20`).

## LLM run details

_To be completed from the laptop run (`runs/<run_id>/run_info.json`)._

| setting | value |
|---|---|
| runtime | Ollama _(version)_ on _(platform)_ |
| model | _(tag and digest)_ |
| temperature / seed | 0 / 0 |
| context window | `num_ctx` 8192, set explicitly (Ollama's default is smaller and truncates silently) |
| structured output | JSON schema generated from the Pydantic model `LLMExtraction` |
| input | start of the document up to the end of section 1.1 (340–580 characters for the samples) |
| prompt | `PROMPT_VERSION = "v1"` in `sds_extractor/llm.py`: copy values exactly as written, exclude UFI/article codes, ignore print and issue dates, return null instead of guessing |

## Logs and run information

Every run writes its own folder `runs/<timestamp>_<mode>/`, so runs never overwrite each other:

- `results.json`, `results.csv`: one record per document, with the source of each value, status and warnings
- `run.log`: per document, which label matched, which codes were found, what the LLM proposed and why anything was rejected
- `run_info.json`: time, mode, Python and package versions, platform, model, settings and prompt version
- `evaluation.md`: comparison with `data/gold.json` (written by `evaluate.py`)

## Questions for stakeholders

1. Should supplemental EUH statements count? EUH210 ("safety data sheet available on request") is not a hazard.
2. Is the article code printed with the trade name part of the name, or a separate identifier?
3. What should happen when an SDS has no revision date?
4. When a product has several SDSs (languages, versions), which one is the master?
5. Is the file name an asset ID that links to the product record?
6. Should a new revision date trigger re-extraction automatically?

## Next steps

1. Larger evaluation set (~50 SDSs across suppliers and languages), with per-field exact match and hazard-code precision/recall, before any production claim.
2. Production on GCP: Gemini on Vertex AI as the LLM client, run on each new SDS upload, send `needs_review` records to a human review queue, and monitor the `needs_review` rate as an early signal of new layouts.
3. CI (GitHub Actions) on Windows, macOS and Linux.
4. Page-level evidence for every extracted value.
5. Labels for more languages (DE, FR) once sample documents are available.
6. OCR fallback for scanned PDFs.

## Use of AI assistants

Claude Code was used to discuss the requirements, test PDF libraries, write the code and tests, and draft this README. Verification: the expected values in `data/gold.json` were checked by hand against the PDFs; three PDF libraries were compared on all 9 values; the tests cover the guardrails (invented values rejected, print date flagged); and the pipeline was run from a clean copy with Python 3.10.

## Time spent

_Approx. X hours in total._
