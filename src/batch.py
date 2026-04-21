from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from src.parser import X12Parser


DEFAULT_GLOB_PATTERNS = ("*.edi", "*.x12")
OPTIONAL_TEXT_GLOB_PATTERNS = ("*.txt",)
MAX_BATCH_FILES = 1000


def discover_input_files(
    path: Path,
    patterns: Iterable[str] | None = None,
    include_text_files: bool = False,
    max_files: int = MAX_BATCH_FILES,
) -> list[Path]:
    patterns = tuple(patterns or DEFAULT_GLOB_PATTERNS)
    if include_text_files:
        patterns = patterns + OPTIONAL_TEXT_GLOB_PATTERNS
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(f"Input path not found: {path}")
    if not path.is_dir():
        raise ValueError(f"Input path must be a file or directory: {path}")

    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in patterns:
        for candidate in sorted(path.rglob(pattern)):
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                files.append(candidate)
                if len(files) > max_files:
                    raise ValueError(
                        f"Input directory yielded more than {max_files} candidate files. "
                        "Refine the directory contents or raise the batch file limit."
                    )
    return files


def _to_serializable(value: Any):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _to_serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_serializable(v) for v in value]
    return str(value)


def append_source_metadata(parsed: dict, source_path: Path) -> dict:
    tagged = dict(parsed)
    tagged["source_file"] = source_path.name
    tagged["source_path"] = str(source_path)
    return tagged


def parse_inputs(paths: Iterable[Path]) -> tuple[list[dict], list[dict]]:
    parsed_documents: list[dict] = []
    failures: list[dict] = []
    for input_path in paths:
        try:
            parser = X12Parser.from_file(input_path)
            parsed = append_source_metadata(parser.to_dict(), input_path)
            parsed_documents.append(parsed)
        except (OSError, UnicodeDecodeError, ValueError) as exc:  # pragma: no cover
            failures.append(
                {
                    "source_file": input_path.name,
                    "source_path": str(input_path),
                    "error": str(exc),
                }
            )
    return parsed_documents, failures


def build_batch_json(documents: list[dict], failures: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "batch": True,
        "file_count": len(documents),
        "failed_file_count": len(failures),
        "source_files": [doc.get("source_path", "") for doc in documents],
        "failures": failures,
        "documents": documents,
    }


def build_batch_summary(documents: list[dict], failures: list[dict]) -> dict:
    return {
        "files_parsed": len(documents),
        "files_failed": len(failures),
        "transactions_total": sum(
            len(fg.get("transactions", []))
            for doc in documents
            for ic in doc.get("interchanges", [])
            for fg in ic.get("functional_groups", [])
        ),
        "claims_835_total": sum(
            len(ts.get("summary", {}).get("claims", []))
            for doc in documents
            for ic in doc.get("interchanges", [])
            for fg in ic.get("functional_groups", [])
            for ts in fg.get("transactions", [])
            if ts.get("set_id") == "835"
        ),
        "claims_837_total": sum(
            len(ts.get("summary", {}).get("claims", []))
            for doc in documents
            for ic in doc.get("interchanges", [])
            for fg in ic.get("functional_groups", [])
            for ts in fg.get("transactions", [])
            if ts.get("set_id") == "837"
        ),
    }
