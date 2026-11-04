"""Command line entry point: python -m sds_extractor [input_dir] [--llm]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .llm import OllamaClient
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sds_extractor",
        description="Extract trade name, revision date and hazard statements from SDS PDFs.",
    )
    parser.add_argument("input_dir", nargs="?", default="data/input", type=Path,
                        help="folder with SDS PDFs (default: data/input)")
    parser.add_argument("--out", default="runs", type=Path,
                        help="folder for run outputs (default: runs)")
    parser.add_argument("--llm", action="store_true",
                        help="also use a local Ollama model for trade name and revision date")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model tag (default: qwen2.5:7b)")
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    args = parser.parse_args(argv)

    # Avoid crashes when a Windows console cannot print characters such as "≥".
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if not args.input_dir.is_dir():
        print(f"Input folder not found: {args.input_dir}", file=sys.stderr)
        return 2

    llm, unavailable = None, None
    if args.llm:
        client = OllamaClient(args.model, host=args.ollama_host)
        unavailable = client.check_available()
        llm = None if unavailable else client

    run_dir = run(args.input_dir, args.out, llm=llm, llm_unavailable=unavailable)
    print(f"\nResults: {run_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
