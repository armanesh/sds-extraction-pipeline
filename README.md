# SDS extraction pipeline

Extracts **trade name**, **revision date** and **hazard statements** from Safety Data Sheet (SDS) PDFs into structured data (JSON and CSV) for import into a master data system.

[![tests](https://github.com/armanesh/sds-extraction-pipeline/actions/workflows/tests.yml/badge.svg)](https://github.com/armanesh/sds-extraction-pipeline/actions/workflows/tests.yml)

## Results

| document | trade name | revision date | hazard statements | status |
|---|---|---|---|---|
| assSDS-120636860 | Super Silicone Kitchen ¹ | 15/07/2026 | EUH208, EUH210 | ok |
| assSDS-123006278 | Kroon-Oil Fuel Optimix 2T | 21/07/2026 | H224, H304, H315, H336, H411 | ok |
| assSDS-128374293 | BISON KIT TRANSPARANT ¹ | 20/04/2026 | H225, H319, H336, EUH066 | ok |

¹ The page shows the supplier's article description printed over this name; see [Findings](#findings).

Scored against the checked answers in [`data/gold.json`](data/gold.json); "LLM alone" is the model's own proposal before guardrails:

| documents | run | trade name | revision date | hazard codes (precision, recall) | LLM alone: name, date |
|---|---|---|---|---|---|
| 3 assignment SDSs | [rules](runs/20261105-093733_rules_input/evaluation.md) | 3/3 | 3/3 | 11/11, 11/11 | — |
| | [rules + qwen2.5:7b](runs/20261105-093739_llm-qwen2.5-7b_input/evaluation.md) | 3/3 | 3/3 | 11/11, 11/11 | 3/3, 3/3 |
| 2 extra SDSs (German, English) | [rules](runs/20261105-093735_rules_extra/evaluation.md) | 1/2 | 0/2 | 8/8, 8/8 | — |
| | [rules + qwen2.5:7b](runs/20261105-093854_llm-qwen2.5-7b_extra/evaluation.md) | 2/2 | 1/2 | 8/8, 8/8 | 2/2, 1/2 |

On the assignment SDSs the LLM only confirms the rules. The two extra public SDSs in [`data/extra`](data/extra/SOURCES.md), not part of the assignment and not used for tuning, show where it matters: on the German one the rules find neither name nor date, and the LLM supplies both correctly. Where neither method finds a value, the record stays empty and `needs_review`. Five documents are a correctness check, not an accuracy estimate.

## Quick start

Python 3.10+; the default run needs no network, model or API key.

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m sds_extractor        # data/input -> runs/<timestamp>_rules_input/
.venv/bin/python -m pytest -q            # 20 tests
```

```powershell
# Windows (no venv activation needed)
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m sds_extractor
.venv\Scripts\python -m pytest -q
```

Other SDSs: `python -m sds_extractor path/to/pdfs`. LLM mode with local [Ollama](https://ollama.com): `ollama pull qwen2.5:7b`, then add `--llm`; without Ollama the run logs why and uses rules only. Score a run: `python evaluate.py runs/<run_id>/results.json`. The code only reads the PDFs and writes under `runs/`; its only network call is to Ollama on `localhost`.

## How it works

```
PDF → text (pypdf) → sections 1.1 and 2.2 by number → extract → validate / reconcile → JSON, CSV, log
```

Sections are found by number, which is the same in every language (REACH 16-section structure).

| field | method | why |
|---|---|---|
| hazard statements | regex `H`/`EUH` + 3 digits, **section 2.2 only** | the format is fully specified; an LLM could only invent codes |
| trade name | label rule + optional LLM | labels vary by supplier and language |
| revision date | label rule + optional LLM; code formats dd/mm/yyyy | telling revision from print/issue dates needs interpretation, formatting does not |

**Not used:** LLM-only extraction (invented or section-3 codes), RAG (section locations are known, and similarity search would also return section 3's ingredient codes), an agent (the flow is fixed).

**Guardrails.** The LLM returns a Pydantic-validated JSON object; a value counts only if it appears verbatim in the model's input (dates must also be real dates). Rules and LLM are then reconciled: agree → `rule+llm`; disagree → rule value, `needs_review`; one found → that value; none → empty, `needs_review`. Status `error` means e.g. section 2.2 was not found. `hazard_statements` is `""` for "no codes in 2.2" and `null` for "could not read".

**Success criteria:** every field matches the checked value, no code from outside section 2.2, no unchecked LLM value, runs anywhere without a model (CI: Linux and Windows, Python 3.10 and 3.13).

## Decisions and assumptions

- **pypdf**, after testing it against PyMuPDF and pdfplumber on all 9 values: pdfplumber garbles the two overlapping trade names, the others got 9/9; pypdf is pure Python and permissively licensed (PyMuPDF is AGPL).
- **Trade name** = the commercial name on the label line in 1.1. The article description printed over it is a product identifier (pack size and codes such as `300ML*12`, also heading every page with the article number), which the brief excludes, as it does the UFI.
- **Revision date** = only a date with a revision label, read day-first. Print, issue and "replaces version" dates are ignored, never used as a substitute.
- **Hazard statements** = every H/EUH code in 2.2, including EUH codes under "Aanvullende gegevens" (supplemental), since the brief includes the EUH format. Counting only those under "Gevarenaanduidingen" would give none for assSDS-120636860 and drop EUH066 from assSDS-128374293.
- **Code format** as in the brief: `H360FD` would be reported as `H360` (none in the samples).
- **document_id** is the file name, which looks like an asset ID that could link to products.
- **The extra SDSs were not used for tuning** (e.g. `Revision:` was not added to the date labels), so they stay an unseen check.

## Findings

- **Page and text layer disagree on two trade names.** A white box covers `Super Silicone Kitchen` / `BISON KIT TRANSPARANT`, with the article description `GRF SILICONE S-200 TR CQ 300ML*12 L001` / `BIS CONTACT KIT TR BD 100ML*6 NLFR` printed on top. Readers see the description; text extraction, and so any LLM, sees the covered name. Found by checking the answers on rendered page images.
- Searching the whole document instead of 2.2 gives 12 codes instead of 2 for assSDS-120636860 and adds ingredient codes to the other two.
- assSDS-128374293 prints `Afdrukdatum: 08.07.2026 herzien op: 20.04.2026`; a test checks that an LLM choosing the print date is flagged.
- **German extra SDS:** the name sits under "Produktidentifikator" without a label, and the date is "Überarbeitet am" among three other dates. Rules found neither; the LLM found both. The file also holds a second SDS (component B); values come from the first.
- **English extra SDS:** `Revision: 07.07.2025` is an unknown label, and the LLM returned no date although it was in its input, probably because the print date is identical. Result: empty and `needs_review`, since guardrails prevent wrong values, not missing ones.
- Comparing PDF libraries exposed a regex bug: pypdf returns `H225Licht…` without a space, which a word-boundary pattern silently missed. Fixed, with a regression test.

## Known limitations

- Five documents (three Dutch, one German, one English): other languages and layouts are untested.
- Text hidden under shapes is not detected (the two documents above are `ok`); a PDF with several SDSs is read as one.
- The LLM can miss a value that is present; a two-line trade name is cut to its first line.
- Only numeric dates are recognised; documents without numbered sections, and scanned PDFs, end as `error`.

## LLM run details

From [`run_info.json`](runs/20261105-093739_llm-qwen2.5-7b_input/run_info.json):

| setting | value |
|---|---|
| runtime | Ollama 0.40.14, local, Windows 11 laptop (16 GB RAM), Python 3.13.3 |
| model | `qwen2.5:7b` (7.6B, Q4_K_M, digest `845dbda0ea48…`): open, multilingual, reliable JSON, runs on a laptop |
| temperature / seed | 0 / 0 |
| context window | `num_ctx` 8192, set explicitly so a long prompt is never cut off silently |
| structured output | JSON schema from the Pydantic model `LLMExtraction` |
| input | document start to end of section 1.1 (330–580 characters here) |
| prompt | `v1` in `sds_extractor/llm.py`: copy values exactly, exclude UFI and article codes, ignore print and issue dates, return null rather than guess |
| speed and scale | rules under 1 s per document, LLM 9–17 s on this laptop; for 10,000 SDSs that is minutes versus about two days, so production would run the LLM in parallel on a hosted model |

## Output, logs and run information

Each record has `document_id`, `source_file`, `file_sha256`, `trade_name`, `trade_name_source`, `revision_date`, `revision_date_source`, `hazard_statements`, `status`, `warnings`, and the LLM's raw proposals `llm_trade_name` and `llm_revision_date`. Each run writes its own `runs/<timestamp>_<mode>_<input folder>/` with `results.json`, `results.csv`, `run.log` (labels matched, codes found, LLM proposals and rejections), `run_info.json` (versions, platform, model, settings) and `evaluation.md`.

## Questions for stakeholders

1. Trade name: the commercial name, or the article description printed over it?
2. Should supplemental EUH statements count? EUH210 ("SDS available on request") is not a hazard.
3. What should happen when an SDS has no revision date?
4. When a product has several SDSs (languages, versions), which is the master?
5. Is the file name an asset ID that links to the product record?
6. Should a new revision date trigger re-extraction?

## Next steps

1. Detect text hidden under shapes and report both values with `needs_review`.
2. A labelled set of ~50 SDSs across suppliers and languages; measure, then extend the label lists where it shows gaps (e.g. `Revision:`, German labels).
3. Split PDFs that contain several SDSs.
4. Production on GCP: Gemini on Vertex AI, extraction on each new SDS, a review queue for `needs_review`, and monitoring of its rate as a signal of new layouts.
5. Later: RAG over free-text sections such as firefighting measures, for questions like "which stored products must not be extinguished with water?". Also page-level evidence per value and OCR for scanned PDFs.

## Use of AI assistants

I used Claude Code as a coding assistant: under my direction it wrote most of the code and tests and drafted this README, and it helped with debugging. I chose the approach after discussing the alternatives with it, reviewed each step, and am responsible for the result.

Verification: the expected values were checked on rendered page images and by eye in the PDFs (this exposed the covered trade names); comparing three PDF libraries exposed a regex bug; the tests cover the guardrails; two public SDSs not used for tuning test other languages and layouts; and CI runs the tests on Linux and Windows.

## Time spent

Approx. 3 h 48 min in total: reading the brief and the documents, design decisions, implementation (with Claude Code as coding assistant), verification and documentation.
