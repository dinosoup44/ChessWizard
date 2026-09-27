"""Read-only summary of local human judgments; never scores or changes analyzers."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from human_analyzer_review_repository import DEFAULT_REVIEW_PATH, HumanReviewRepository, ReviewStorageError
from human_analyzer_reviews import summarize_reviews


def main(argv: list[str] | None = None) -> int:
    """Summarize an explicitly selected local review file without modifying it.

    Args:
        argv: Optional command-line arguments; defaults to the process arguments.

    Returns:
        Zero on success, or two when the review file cannot be read safely.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_REVIEW_PATH)
    parser.add_argument("--json", action="store_true", help="Print structured summary")
    args = parser.parse_args(argv)
    try:
        summary = summarize_reviews(HumanReviewRepository(args.path).load())
    except ReviewStorageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    print(f"Reviewed total: {summary['reviewed_total']}")
    for heading, key in (("Verdicts", "verdicts"), ("By tactic type", "by_tactic_type"), ("By review set", "by_review_set"), ("By relation", "by_relation")):
        print(f"\n{heading}:")
        for label, count in summary[key].items():
            print(f"  {label}: {count}")
    print("\nNon-PASS cases:")
    for row in summary["non_pass"]:
        case = row["case"]
        identity = f"Candidate {case['candidate_id']}" if case["candidate_id"] is not None else f"Audit {case['audit_case_id']}"
        anchor = f"move ID {case['move_id']}" if case["move_id"] is not None else "game-level anchor (not a chess move)"
        print(f"  {identity} · game {case['game_id']} · {anchor} · {row['verdict']}")
        print(f"    {row['note'] or '(no note)'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
