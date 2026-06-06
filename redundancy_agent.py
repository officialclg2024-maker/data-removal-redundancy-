from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from app import append_unique_record, init_db, validate_record


class RedundancyRemovalAgent:
    """Agent that validates incoming records and keeps only verified data."""

    def __init__(self) -> None:
        init_db()

    def inspect(self, source: str, content: str) -> dict[str, object]:
        result = validate_record(source, content)
        return {
            **asdict(result),
            "source": source,
            "content": content,
            "action": "preview_only",
        }

    def submit(self, source: str, content: str) -> dict[str, object]:
        result = append_unique_record(source, content)
        return {
            **asdict(result),
            "source": source,
            "content": content,
            "action": "stored" if result.status == "accepted" else "blocked",
        }

    def process_batch(
        self,
        records: Iterable[dict[str, str]],
        dry_run: bool = False,
    ) -> list[dict[str, object]]:
        decisions = []
        for record in records:
            source = record.get("source", "batch_import")
            content = record.get("content", "")
            decision = self.inspect(source, content) if dry_run else self.submit(source, content)
            decisions.append(decision)
        return decisions


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if "content" not in (reader.fieldnames or []):
            raise ValueError("CSV input must include a 'content' column.")
        return [dict(row) for row in reader]


def read_json(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("JSON input must be a list of records.")
    return [dict(item) for item in data]


def write_report(path: Path, decisions: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(decisions, file, indent=2)


def load_records(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".csv":
        return read_csv(path)
    if path.suffix.lower() == ".json":
        return read_json(path)
    raise ValueError("Input file must be .csv or .json.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate data entries and remove redundant submissions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Preview one record.")
    inspect_parser.add_argument("--source", required=True)
    inspect_parser.add_argument("--content", required=True)

    submit_parser = subparsers.add_parser("submit", help="Validate and store one record.")
    submit_parser.add_argument("--source", required=True)
    submit_parser.add_argument("--content", required=True)

    batch_parser = subparsers.add_parser("batch", help="Process CSV or JSON records.")
    batch_parser.add_argument("--input", required=True, type=Path)
    batch_parser.add_argument("--report", default=Path("reports/agent_report.json"), type=Path)
    batch_parser.add_argument("--dry-run", action="store_true")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    agent = RedundancyRemovalAgent()

    if args.command == "inspect":
        decision = agent.inspect(args.source, args.content)
        print(json.dumps(decision, indent=2))
        return

    if args.command == "submit":
        decision = agent.submit(args.source, args.content)
        print(json.dumps(decision, indent=2))
        return

    records = load_records(args.input)
    decisions = agent.process_batch(records, dry_run=args.dry_run)
    write_report(args.report, decisions)
    print(json.dumps({"processed": len(decisions), "report": str(args.report)}, indent=2))


if __name__ == "__main__":
    main()
