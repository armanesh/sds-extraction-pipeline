# SDS extraction pipeline

Extracts **trade name**, **revision date** and **hazard statements** from Safety Data Sheet (SDS) PDFs into structured data (JSON and CSV) for import into a master data system.

## Results

| document | trade name | revision date | hazard statements | status |
|---|---|---|---|---|
| assSDS-120636860 | Super Silicone Kitchen ¹ | 15/07/2026 | EUH208, EUH210 | ok |
| assSDS-123006278 | Kroon-Oil Fuel Optimix 2T | 21/07/2026 | H224, H304, H315, H336, H411 | ok |
| assSDS-128374293 | BISON KIT TRANSPARANT ¹ | 20/04/2026 | H225, H319, H336, EUH066 | ok |

All values match the checked answers in [`data/gold.json`](data/gold.json) in both runs: [rules only](runs/20261104-073638_rules/evaluation.md) (Linux) and [rules + qwen2.5:7b](runs/20261104-133153_llm-qwen2.5-7b/evaluation.md) (Windows 11): 3/3 trade names, 3/3 dates, hazard codes 11/11 precision and recall. In the LLM run the model agreed with the rules on all six free-text values, so here it confirmed rather than added; its role is labels and layouts the rules do not know. Three documents are a correctness check, not an accuracy estimate.

¹ The page shows a different text here: the supplier printed its article description over the trade name. See [Findings](#findings).

## Quick start

Python 3.10+. The default run needs no network, model or API key.

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m sds_extractor        # data/input -> runs/<timestamp>_rules/
.venv/bin/python -m pytest -q            # 17 tests
```

```powershell
# Windows (no venv activation needed)
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m sds_extractor
.venv\Scripts\python -m pytest -q
```

Optional LLM mode with local [Ollama](https://ollama.com): `ollama pull qwen2.5:7b`, then add `--llm` (`--model <tag>` for another model). If Ollama is not available the run logs why and continues with rules only. Score a run with `python evaluate.py runs/<run_id>/results.json`.

The code only reads the input PDFs and writes a new folder under `runs/`; the only network call is to Ollama on `localhost` in `--llm` mode.

## How it works

```
PDF → text (pypdf) → sections 1.1 and 2.2 by number → extract → validate / reconcile → JSON, CSV, log
```

Sections are found by number, not heading: SDSs follow the REACH 16-section structure, so "2.2" is the same in every language.

| field | method | why |
|---|---|---|
| hazard statements | regex `H`/`EUH` + 3 digits, **section 2.2 only** | the format is fully specified, so a regex is exact; an LLM could only invent codes |
| trade name | label rule (`Handelsnaam`, `Trade name`, …) + optional LLM | labels vary by supplier and language; the LLM covers unknown ones |
| revision date | label rule + optional LLM; code formats dd/mm/yyyy | choosing the revision date over print/issue dates needs interpretation, formatting does not |

**Not used:** LLM-only extraction (risk of invented codes and of section-3 codes), RAG (section locations are known, and similarity search would also return section 3, which lists ingredient H-codes), an agent (the flow is fixed and linear).

**Guardrails.** The LLM returns a Pydantic-validated JSON object. A value is accepted only if it appears verbatim in the text the model was given (and, for dates, is a real date). Then rules and LLM are reconciled: same value → `rule+llm`; different values → rule value kept, status `needs_review`; only one found → that value; none → empty, `needs_review`.

**Status** is `ok`, `needs_review` or `error` (e.g. section 2.2 not found). `hazard_statements` is `""` when section 2.2 lists no codes and `null` when it could not be read: "no hazards" and "could not read" are different answers.

**Success criteria:** every field matches the checked value; no hazard code from outside section 2.2; no LLM value accepted without a check; runs on any OS without a model (tests pass on Linux with Python 3.10/3.13 and Windows 11 with 3.13).

## Decisions and assumptions

- **pypdf** for text: tested against PyMuPDF and pdfplumber on all 9 values. pdfplumber merges the covered trade name and the text printed over it into one unreadable string; pypdf and PyMuPDF got 9/9. pypdf is pure Python and permissively licensed (PyMuPDF is AGPL).
- **Trade name** = the commercial name on the label's line in section 1.1. The article description printed over it in two documents is not reported, because the brief defines the trade name as the commercial name and excludes product identifiers: the description holds pack size and internal codes (`300ML*12`, `L001`) and also heads every page with the article number (`6315510 - …`). Pack and SKU details belong to the inventory record linked later. The UFI under the name in assSDS-123006278 is excluded likewise.
- **Revision date** = only a date with a revision label; print, first-issue and "replaces version of" dates are ignored. Dates are read day-first. If none is found the field stays empty; the print date is never a substitute.
- **Hazard statements** = every H/EUH code in section 2.2, including EUH codes listed under "Aanvullende gegevens" (supplemental information), since the definition includes the EUH format. A strict reading (only under "Gevarenaanduidingen") would give no codes for assSDS-120636860 and drop EUH066 from assSDS-128374293.
- **Code format** follows the brief (`H` + 3 digits): `H360FD` would be reported as `H360` (none in section 2.2 of the samples).
- **document_id** is the file name, which looks like an internal asset ID and could link records to products.

## Findings

- **The page and the text layer disagree on two trade names.** Section 1.1 was written as `Super Silicone Kitchen` / `BISON KIT TRANSPARANT`; a white box was then drawn over it and the supplier's article description printed on top in another font, on page 1 and in every page header. A reader sees `GRF SILICONE S-200 TR CQ 300ML*12 L001` / `BIS CONTACT KIT TR BD 100ML*6 NLFR`; text extraction, and so any LLM reading the text, sees only the covered name. Found by checking the expected values against rendered page images rather than extracted text.
- Searching the whole document instead of section 2.2 gives 12 codes instead of 2 for assSDS-120636860, adds EUH066 (an ingredient's code) to assSDS-123006278, and adds H317, H361, H400 and H410 to assSDS-128374293.
- assSDS-128374293 prints `Afdrukdatum: 08.07.2026 herzien op: 20.04.2026`. A test checks that an LLM picking the print date is flagged.
- Comparing PDF libraries exposed a bug in the first hazard-code regex: pypdf returns `H225Licht…` without a space, which a word-boundary pattern silently missed. Fixed, with a regression test.

## Known limitations

- Three samples, two layouts, all Dutch: other languages and layouts are untested.
- Text hidden under drawn shapes is not detected; the two documents above are reported `ok`.
- A trade name spanning two lines is cut to the first line (only an LLM disagreement would flag it).
- Only numeric dates are recognised (`15.07.2026`, `21-7-2026`, `2026-04-20`).
- Documents without numbered section headings, and scanned PDFs (no OCR), end with status `error`.

## LLM run details

From [`run_info.json`](runs/20261104-133153_llm-qwen2.5-7b/run_info.json):

| setting | value |
|---|---|
| runtime | Ollama 0.40.14, local, Windows 11 laptop (16 GB RAM), Python 3.13.3 |
| model | `qwen2.5:7b` (7.6B, Q4_K_M, digest `845dbda0ea48…`): open, multilingual, reliable JSON, runs on an ordinary laptop |
| temperature / seed | 0 / 0 |
| context window | `num_ctx` 8192, set explicitly (Ollama's smaller default truncates silently) |
| structured output | JSON schema from the Pydantic model `LLMExtraction` |
| input | document start to end of section 1.1 (340–580 characters here) |
| prompt | `v1` in `sds_extractor/llm.py`: copy values exactly as written, exclude UFI and article codes, ignore print and issue dates, return null rather than guess |
| run time | ~95 s for three documents, including model load |

## Logs and run information

Each run writes `runs/<timestamp>_<mode>/`, so runs never overwrite each other: `results.json` / `results.csv` (one record per document with value sources, status and warnings), `run.log` (which label matched, codes found, LLM proposals and rejections), `run_info.json` (versions, platform, model, settings, prompt version) and `evaluation.md`.

## Questions for stakeholders

1. Trade name: the commercial name, or the article description printed over it on the page?
2. Should supplemental EUH statements count? EUH210 ("SDS available on request") is not a hazard.
3. What should happen when an SDS has no revision date?
4. When a product has several SDSs (languages, versions), which one is the master?
5. Is the file name an asset ID that links to the product record?
6. Should a new revision date trigger re-extraction?

## Next steps

1. Detect text hidden under drawn shapes and report both values with `needs_review`.
2. A larger evaluation set (~50 SDSs across suppliers and languages) before any accuracy claim.
3. Production on GCP: Gemini on Vertex AI as the LLM client, extraction on each new SDS, a human review queue for `needs_review`, and monitoring of the `needs_review` rate as an early signal of new layouts.
4. CI on Windows, macOS and Linux; page-level evidence per value; labels for more languages once samples exist; OCR for scanned PDFs.

## Use of AI assistants

I worked with Claude Code as a coding assistant so that the coding itself stayed clean and consistent: under my direction it wrote most of the code and tests and drafted this README. I reviewed each step and used it to help with debugging, for example the hazard-code regex bug and a test import-path issue. I stayed involved throughout, since I am responsible for the result.

The approach came out of a discussion. Some ideas were mine: thinking beyond this task (retrieval over many SDSs, e.g. RAG for questions such as "which stored products react with water?", could be useful later, but we agreed it adds nothing to extracting fields whose location is known), requiring that the pipeline runs on a reviewer's machine without any model, and comparing all three PDF libraries instead of trusting one. Others were Claude's suggestions, and we settled on the design together. The decisions and their reasons are in this README.

Verification:
- The expected values in `data/gold.json` were checked twice: on page images rendered with Claude Code, which we went through together (this exposed the covered trade names), and separately by me, by eye in the PDFs.
- Comparing three PDF libraries on all values exposed the regex bug.
- The tests cover the guardrails (invented values rejected, print date flagged).
- The pipeline was run from a clean copy with Python 3.10, and the LLM mode on my Windows laptop.

## Time spent

Approx. 3 h 48 min in total: reading the brief and the documents, design decisions, implementation (with Claude Code as coding assistant), verification and documentation.
