"""Optional LLM extractor (Ollama, local) for the two free-text fields.

The LLM only *proposes* a trade name and a revision date. Nothing it returns is
used unless it appears verbatim in the source text (see `is_grounded`) and, for
dates, parses as a real calendar date. Hazard codes are never sent to the LLM:
their format is fully specified, so a regex is exact and cannot hallucinate.
"""

from __future__ import annotations

from typing import Protocol

import requests
from pydantic import BaseModel, Field

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You extract fields from the text of a Safety Data Sheet (SDS).
The text may be in any European language. Return JSON matching the schema.

trade_name: the commercial product name given in section 1.1 (labels such as
"Trade name", "Product name", "Handelsnaam"). Copy it exactly as written: same
spelling, capitalisation and language. Do not include the UFI, article numbers,
product codes or pack sizes, even if they are printed next to or under the name.

revision_date: the date of the latest revision of the SDS (labels such as
"Revision date", "Datum herziening", "herzien op"). Copy it exactly as written,
for example "15.07.2026". Do not return the print date, the date of first issue,
or the date of the version that was replaced.

If a field is not present in the text, return null. Never guess."""


class LLMExtraction(BaseModel):
    """Structured output the model must return (sent to Ollama as a JSON schema)."""

    trade_name: str | None = Field(description="Trade name exactly as written, or null")
    revision_date: str | None = Field(description="Revision date exactly as written, or null")


class LLMClient(Protocol):
    def extract(self, text: str) -> LLMExtraction: ...

    def describe(self) -> dict: ...


class OllamaClient:
    """Minimal client for a local Ollama server (https://ollama.com)."""

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        num_ctx: int = 8192,
        timeout: float = 300,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        # Ollama's default context window is small and silently truncates longer
        # prompts, so it is set explicitly. Our prompts are ~1-2k tokens.
        self.options = {"temperature": 0, "seed": 0, "num_ctx": num_ctx}
        self.timeout = timeout

    def check_available(self) -> str | None:
        """Return None if the server is up and the model is pulled, else a reason."""
        try:
            tags = requests.get(f"{self.host}/api/tags", timeout=5).json()
        except requests.RequestException as exc:
            return f"Ollama is not reachable at {self.host} ({exc.__class__.__name__})"
        names = {m.get("name") for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            return f"model '{self.model}' is not pulled; run: ollama pull {self.model}"
        return None

    def extract(self, text: str) -> LLMExtraction:
        response = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "format": LLMExtraction.model_json_schema(),
                "options": self.options,
                "stream": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return LLMExtraction.model_validate_json(response.json()["message"]["content"])

    def describe(self) -> dict:
        """Run details for run_info.json: model tag, digest, server version, settings."""
        info: dict = {
            "provider": "ollama",
            "model": self.model,
            "host": self.host,
            "options": self.options,
            "prompt_version": PROMPT_VERSION,
        }
        try:
            info["ollama_version"] = requests.get(f"{self.host}/api/version", timeout=5).json().get("version")
            for m in requests.get(f"{self.host}/api/tags", timeout=5).json().get("models", []):
                if m.get("name") in (self.model, f"{self.model}:latest"):
                    info["model_digest"] = m.get("digest")
                    info["model_details"] = m.get("details")
        except requests.RequestException:
            pass
        return info


def _squash(text: str) -> str:
    return " ".join(text.split())


def is_grounded(value: str, source: str) -> bool:
    """True if `value` occurs verbatim in `source` (ignoring line breaks/spacing)."""
    return bool(value.strip()) and _squash(value) in _squash(source)
