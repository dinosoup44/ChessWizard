"""Explicit existing-Fork preview; only insert-once candidate-line cache writes allowed."""
import argparse
from collections import Counter
from contextlib import ExitStack, closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from analysis_engine import LazyScoutEngine
from analysis_safety import create_backup, integrity_check
from analysis_settings import load_profile
from candidate_line_engine import CandidateLineGenerator
from candidate_line_repository import CandidateLineRepository, insert_only_authorizer
from candidate_line_service import CandidateLineService
from candidate_verification import existing_candidates, verify_candidates
from candidate_verification_registry import escalating_fork_verifier
from migrate_candidate_line_cache import validate_schema
from preview_candidate_lines_verification import eligible_candidates, proposed_feedback, file_hash
from tactical_opportunities import opportunity_to_dict


def table_fingerprints(connection):
    """Protect every pre-existing table, including caches and training links, by full row content."""
    result = {}
    tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'engine_candidate_line_cache' ORDER BY name").fetchall()
    for (table,) in tables:
        digest, count = hashlib.sha256(), 0
        quoted = table.replace('"', '""')
        for row in connection.execute(f'SELECT * FROM "{quoted}" ORDER BY rowid'):
            digest.update(repr(tuple(row)).encode("utf-8") + b"\n")
            count += 1
        result[table] = {"count": count, "sha256": digest.hexdigest()}
    return result


def source_hashes(root):
    paths = list(root.glob("*.py"))
    for folder in ("board_analysis", "feedback", "merlin_ui"):
        paths.extend((root/folder).rglob("*.py"))
    return {str(path.relative_to(root)): file_hash(path) for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", choices=("missed_fork",), required=True)
    parser.add_argument("--allow-candidate-line-cache-inserts", action="store_true", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    database, reports = root/"merlin.db", root/"reports"
    result_path = reports/"fork_v31_results.jsonl"
    if result_path.exists():
        raise RuntimeError("Existing preview output must be reviewed before another run")
    profile = load_profile("normal_escalation")
    sources = source_hashes(root)
    previous = json.loads((reports/"fork_v3_multiline_preview.json").read_text(encoding="utf-8"))
    previous_classes = {cid: state for state, ids in previous["candidate_ids_by_classification"].items() for cid in ids}
    started = time.perf_counter()
    with ExitStack() as stack:
        db = stack.enter_context(closing(sqlite3.connect(database)))
        integrity_check(db)
        validate_schema(db)
        rows = existing_candidates(db, args.analysis)
        cursor = db.execute("SELECT * FROM analysis_coverage WHERE analysis_type=?", (args.analysis,))
        coverage = [dict(zip((field[0] for field in cursor.description), row)) for row in cursor]
        eligible, protected = eligible_candidates(rows, coverage)
        prior_ids = set(previous_classes)
        if {row["candidate_id"] for row in eligible} != prior_ids:
            raise RuntimeError("Eligible candidate scope differs from the saved prior preview")
        eligible.sort(key=lambda row: (row["candidate_id"] != 1828, row["candidate_id"] != 1355, row["candidate_id"]))
        before_tables = table_fingerprints(db)
        before_cache = db.execute("SELECT * FROM engine_candidate_line_cache ORDER BY line_set_id").fetchall()
        schema = db.execute("SELECT * FROM sqlite_master ORDER BY type,name").fetchall()
        all_ids = [r[0] for r in db.execute("SELECT candidate_id FROM tactic_candidates ORDER BY candidate_id")]
        backup = create_backup(db, database, "fork_v31_cache_preview")
        before = {"database_sha256": file_hash(database), "database_bytes": database.stat().st_size,
            "tables": before_tables, "all_candidate_ids": all_ids, "cache_rows": len(before_cache),
            "eligible_ids": [row["candidate_id"] for row in eligible], "protected": protected,
            "backup": str(backup), "backup_sha256": file_hash(backup), "profile": asdict(profile),
            "source_hashes": sources, "quick_check": "ok", "foreign_key_check": []}
        (reports/"fork_v31_before.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
        db.set_authorizer(insert_only_authorizer)
        repository = CandidateLineRepository(db)
        engine = LazyScoutEngine(stack, root)
        generator = CandidateLineGenerator(engine)
        breadth = CandidateLineService(generator, write_store=repository)
        verification = CandidateLineService(generator, write_store=repository)
        totals, metrics, comparisons = Counter(), Counter(), Counter()
        classifications, request_counts, search_counts = {}, [], []
        last_searches = 0
        with result_path.open("x", encoding="utf-8") as output:
            def record(row, result, completed, total):
                nonlocal last_searches
                details = result.details
                classification = details.get("classification", "error")
                normal = details.get("normal_robustness", {}).get("classification", classification)
                esc = details.get("escalation", {})
                branches = esc.get("branches_escalated", 0)
                totals[classification] += 1
                classifications[row["candidate_id"]] = classification
                metrics["candidates_escalated"] += bool(branches)
                metrics["total_escalated_branches"] += branches
                metrics["clear_without_escalation"] += not branches and classification in {"verified", "verified_payoff_changed", "rejected"}
                metrics["resolved_by_escalation"] += normal == "ambiguous" and classification in {"verified", "verified_payoff_changed", "rejected"}
                metrics["still_ambiguous_after_escalation"] += bool(branches) and classification == "ambiguous"
                old = previous_classes[row["candidate_id"]]
                comparisons["previous_ambiguous_resolved"] += old == "ambiguous" and classification in {"verified", "verified_payoff_changed", "rejected"}
                comparisons["previous_clear_now_ambiguous"] += old != "ambiguous" and classification == "ambiguous"
                comparisons["classification_changed"] += old != classification
                searches = verification.stats["engine_searches"] - last_searches
                last_searches = verification.stats["engine_searches"]
                if branches:
                    request_counts.append(esc.get("distinct_requests", 0))
                    search_counts.append(searches)
                saved = {"candidate_id": row["candidate_id"], "game_id": row["game_id"],
                    "source_game_id": row["source_game_id"], "move_number": row["move_number"], "color": row["color"],
                    "old_multiline_classification": old, "state": result.state, "details": details,
                    "verification_engine_searches": searches,
                    "candidate": result.candidate,
                    "opportunity": opportunity_to_dict(result.opportunity) if result.opportunity else None,
                    "feedback": proposed_feedback(row, result)}
                db.commit()
                output.write(json.dumps(saved)+"\n"); output.flush()
                if row["candidate_id"] == 1828:
                    (reports/"fork_v31_qxb7.json").write_text(json.dumps(saved, indent=2), encoding="utf-8")
                progress = {"completed": completed, "total": total, "outcomes": dict(totals),
                    "metrics": dict(metrics), "breadth_cache": dict(breadth.stats),
                    "verification_cache": dict(verification.stats), "elapsed_seconds": round(time.perf_counter()-started, 2)}
                (reports/"fork_v31_progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
                print(json.dumps(progress), flush=True)
            verify_candidates(eligible, escalating_fork_verifier(profile, verification), breadth, record)
        integrity_check(db)
        after_tables = table_fingerprints(db)
        assert before_tables == after_tables, "Protected table contents changed"
        assert schema == db.execute("SELECT * FROM sqlite_master ORDER BY type,name").fetchall()
        assert before_cache == db.execute("SELECT * FROM engine_candidate_line_cache WHERE line_set_id<=? ORDER BY line_set_id",
            (max((row[0] for row in before_cache), default=0),)).fetchall()
        assert sources == source_hashes(root), "Production sources changed during preview"
        count, payload = db.execute("SELECT count(*),coalesce(sum(length(CAST(payload_json AS BLOB))),0) FROM engine_candidate_line_cache").fetchone()
        summary = {"total_existing_fork_rows": len(rows), "eligible": len(eligible), "protected": protected,
            "outcomes": dict(totals), "metrics": dict(metrics), "comparison_with_prior": dict(comparisons),
            "breadth_cache": dict(breadth.stats), "verification_cache": dict(verification.stats),
            "verification_requests_per_escalated_candidate": {"average": sum(request_counts)/len(request_counts) if request_counts else 0, "max": max(request_counts, default=0)},
            "verification_searches_per_escalated_candidate": {"average": sum(search_counts)/len(search_counts) if search_counts else 0, "max": max(search_counts, default=0)},
            "tables_before": before_tables, "tables_after": after_tables, "all_candidate_ids_preserved": len(all_ids),
            "protected_tables_unchanged": True, "existing_cache_rows_unchanged": True,
            "cache_rows_before": len(before_cache), "cache_rows_after": count, "cache_payload_bytes": payload,
            "database_bytes_before": before["database_bytes"], "database_bytes_after": database.stat().st_size,
            "database_sha256_before": before["database_sha256"], "database_sha256_after": file_hash(database),
            "quick_check": "ok", "foreign_key_check": [], "source_hashes": sources,
            "elapsed_seconds": time.perf_counter()-started,
            "candidate_ids_by_classification": {state: [cid for cid, value in classifications.items() if value==state] for state in totals}}
        (reports/"fork_v31_preview.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({k:v for k,v in summary.items() if k not in {"source_hashes","tables_before","tables_after","candidate_ids_by_classification"}}, indent=2), flush=True)


if __name__ == "__main__":
    main()
