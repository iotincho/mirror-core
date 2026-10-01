"""Compare experimental link reports to a manually annotated document-pair set."""

import argparse
import json
from pathlib import Path

SYMMETRIC_RELATION_TYPES = {"SAME_REFERENT", "IN_TENSION"}


def key(item: dict) -> tuple[str, str, str]:
    left, right = item["source_document_id"], item["target_document_id"]
    if item["relation_type"] in SYMMETRIC_RELATION_TYPES:
        left, right = sorted((left, right))
    return left, right, item["relation_type"]


def evaluate(expected: list[dict], reports: list[dict]) -> dict:
    gold = {key(item) for item in expected}
    predicted = {key(link) for report in reports for link in report["links"]}
    correct = gold & predicted
    return {
        "expected": len(gold),
        "predicted": len(predicted),
        "correct": len(correct),
        "precision": len(correct) / len(predicted) if predicted else 0.0,
        "recall": len(correct) / len(gold) if gold else 0.0,
        "false_positives": sorted(predicted - gold),
        "missed": sorted(gold - predicted),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path, help="JSON list of annotated document pairs")
    parser.add_argument("reports", type=Path, nargs="+", help="Saved endpoint responses")
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    print(json.dumps(evaluate(expected, reports), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
