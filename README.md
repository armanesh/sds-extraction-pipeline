# SDS extraction pipeline

Extracts **trade name**, **revision date** and **hazard statements** from Safety Data Sheet (SDS) PDFs into structured data (JSON and CSV) for import into a master data system.

## Results

| document | trade name | revision date | hazard statements | status |
|---|---|---|---|---|
| assSDS-120636860 | Super Silicone Kitchen | 15/07/2026 | EUH208, EUH210 | ok |
| assSDS-123006278 | Kroon-Oil Fuel Optimix 2T | 21/07/2026 | H224, H304, H315, H336, H411 | ok |
| assSDS-128374293 | BISON KIT TRANSPARANT | 20/04/2026 | H225, H319, H336, EUH066 | ok |

All values match the hand-checked answers in [`data/gold.json`](data/gold.json):

| run | trade name | revision date | hazard precision | hazard recall | status |
|---|---|---|---|---|---|
| [rules only](runs/20261104-073638_rules/evaluation.md) (Linux) | 3/3 | 3/3 | 11/11 | 11/11 | 3 ok |
| [rules + qwen2.5:7b](runs/20261104-133153_llm-qwen2.5-7b/evaluation.md) (Windows 11) | 3/3 | 3/3 | 11/11 | 11/11 | 3 ok |

In the LLM run the model agreed with the rules on every trade name and revision date (source `rule+llm` for all six values), so on these samples it confirmed the rules rather than adding anything. Its purpose is labels and layouts the rules do not know. The tests show how its mistakes are handled. Three documents are a correctness check, not an accuracy estimate.

> **Note on two trade names.** In assSDS-120636860 and assSDS-128374293 the supplier has covered the trade name with a white box and printed its article description on top. The page therefore *shows* `GRF SILICONE S-200 TR CQ 300ML*12 L001` and `BIS CONTACT KIT TR BD 100ML*6 NLFR`, while the text layer still contains the commercial names reported above. Why the commercial name is reported, and what is still open, is explained under [Findings](#findings-from-the-documents) and [Decisions](#decisions-and-assumptions).

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
4. Runs on any OS without a model or network access (paths via `pathlib`, all files UTF-8; tests pass on Linux with Python 3.10 and 3.13 and on Windows 11 with Python 3.13).

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

- **PDF library: pypdf.** Tested pypdf, PyMuPDF and pdfplumber on all 9 values. pdfplumber mixes the covered trade name and the article description printed over it into one unreadable string; pypdf and PyMuPDF return the text-layer name and got 9/9. pypdf is pure Python and permissively licensed (PyMuPDF is AGPL).
- **Trade name** = the commercial name in section 1.1, from the label's line only. Where the supplier's article description is printed over it (see Findings), the description is not reported as the trade name, because:
  1. the brief defines the trade name as the *commercial name* and excludes *product identifiers*; the description is an article identifier with pack size and internal codes (`300ML*12`, `L001`), and the same text heads every page together with the article number (`6315510 - …`);
  2. an SDS describes the chemical product, while pack and SKU details belong to the inventory record that is linked to this data later.

  The UFI printed under the name in assSDS-123006278 is excluded for the same reason. This is the most important open question for stakeholders (below).
- **Revision date** = only a date with a revision label. Print date, first-issue date and "replaces version of" dates are ignored. Dates are read day-first (European documents). If no revision date is found the field stays empty; the print date is never used as a substitute.
- **Hazard statements** = every H/EUH code printed in section 2.2. In two documents some EUH codes are listed under "Aanvullende gegevens" (supplemental information) rather than under "Gevarenaanduidingen". The definition explicitly includes the EUH format, so they are included. A stricter reading would give:

  | document | included (this pipeline) | strict reading |
  |---|---|---|
  | assSDS-120636860 | EUH208, EUH210 | _(none: "Niet van toepassing")_ |
  | assSDS-128374293 | H225, H319, H336, EUH066 | H225, H319, H336 |

- **Code format** follows the brief (`H` + 3 digits): a suffix such as `H360FD` would be reported as `H360`. None occur in section 2.2 of the samples.
- **document_id** is the file name; it looks like an internal asset ID and would be the key to link records to products later.

## Findings from the documents

- **What the page shows is not always what the file contains.** In two documents section 1.1 was written as `Handelsnaam: Super Silicone Kitchen` / `BISON KIT TRANSPARANT` (embedded Arial). A white rectangle is then drawn over the name and the supplier's article description is printed on top in another font (Helvetica), on page 1 and in every page header:

  | document | shown on the page | in the text layer (reported) |
  |---|---|---|
  | assSDS-120636860 | GRF SILICONE S-200 TR CQ 300ML*12 L001 | Super Silicone Kitchen |
  | assSDS-128374293 | BIS CONTACT KIT TR BD 100ML*6 NLFR | BISON KIT TRANSPARANT |

  A reader sees only the description; text extraction, and therefore any LLM reading the extracted text, sees only the covered name. This was found by checking the expected values against rendered images of the pages instead of extracted text.
- Searching the whole document instead of section 2.2 gives 12 codes for assSDS-120636860 instead of 2, adds EUH066 to assSDS-123006278 (it belongs to an ingredient), and adds H317, H361, H400 and H410 to assSDS-128374293.
- assSDS-128374293 prints `Afdrukdatum: 08.07.2026 herzien op: 20.04.2026`: the print date is the obvious wrong answer. A test checks that an LLM picking it is flagged.
- Comparing PDF libraries exposed a bug in the first hazard-code regex: pypdf returns `H225Licht…` without a space, and a word-boundary pattern silently missed those codes. The pattern and a regression test were updated.

## Known limitations

- Three samples in two layouts, all Dutch: rules for other languages and layouts are untested.
- Scanned PDFs (no text layer) are reported as errors; there is no OCR.
- Sections are found by numbered headings; documents without them fail with status `error`.
- Text covered by drawn shapes is not detected: for the two documents above the pipeline reports status `ok`, although the page shows a different value. The visual check found it, not the pipeline.
- A trade name spanning two lines is cut to the first line; only an LLM disagreement would flag it.
- Only numeric dates are recognised (`15.07.2026`, `21-7-2026`, `2026-04-20`).

## LLM run details

From [`run_info.json`](runs/20261104-133153_llm-qwen2.5-7b/run_info.json) of the LLM run:

| setting | value |
|---|---|
| runtime | Ollama 0.40.14, local, on a Windows 11 laptop (16 GB RAM), Python 3.13.3 |
| model | `qwen2.5:7b` (Qwen2.5 7.6B, Q4_K_M quantisation, digest `845dbda0ea48…`) |
| why this model | open, multilingual (the SDSs are Dutch), reliable JSON output, and runs on an ordinary 16 GB laptop |
| run time | ~95 s for the three documents, including loading the model (~15–60 s per document) |
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

1. Trade name: the manufacturer's commercial name, or the article description the supplier prints over it on the page? This pipeline reports the commercial name.
2. Should supplemental EUH statements count? EUH210 ("safety data sheet available on request") is not a hazard.
3. What should happen when an SDS has no revision date?
4. When a product has several SDSs (languages, versions), which one is the master?
5. Is the file name an asset ID that links to the product record?
6. Should a new revision date trigger re-extraction automatically?

## Next steps

1. Detect text hidden under drawn shapes (compare the drawing order of text and filled boxes, or OCR the rendered field) and report both values with status `needs_review`.
2. Larger evaluation set (~50 SDSs across suppliers and languages), with per-field exact match and hazard-code precision/recall, before any production claim.
3. Production on GCP: Gemini on Vertex AI as the LLM client, run on each new SDS upload, send `needs_review` records to a human review queue, and monitor the `needs_review` rate as an early signal of new layouts.
4. CI (GitHub Actions) on Windows, macOS and Linux.
5. Page-level evidence for every extracted value.
6. Labels for more languages (DE, FR) once sample documents are available.
7. OCR fallback for scanned PDFs.

## Use of AI assistants

Claude Code was used to discuss the requirements, test PDF libraries, write the code and tests, draft this README, and carry out the Windows LLM run on my laptop from written step-by-step instructions. Verification: the expected values in `data/gold.json` were checked against images of the rendered PDF pages, independently of the text extraction (this is how the covered trade names were found); three PDF libraries were compared on all 9 values; the tests cover the guardrails (invented values rejected, print date flagged); and the pipeline was run from a clean copy with Python 3.10.

## Time spent

Approx. 3 h 48 min in total: reading the brief and the documents, design decisions, implementation (with Claude Code as coding assistant), verification and documentation.
