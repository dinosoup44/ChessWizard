"""Controlled orchestration service used by the central crawler.

Only the saved 10- and 500-game scopes are enabled. Registry adapters calculate; the
position service caches evidence; the repository owns candidate/coverage writes.
"""
from collections import Counter
from contextlib import ExitStack, closing
import json
import sqlite3
import time

from analysis_safety import coverage_rows, protected_snapshot, integrity_check, create_backup
from analysis_engine import DryRunEvidence, LazyScoutEngine
from analysis_planner import plan_negatives, plan_stale_no_hits
from heavy_adapters import dispatch_heavy
from heavy_repository import save_heavy_result
from analysis_scope import heavy_test_game_ids, validation_scope_ids
from tactical_opportunity_repository import read_candidate_opportunity
from tactical_opportunities import opportunity_to_dict


def run_heavy_scope(connection, definitions, moves, game_ids, database_path, decide, *, validation_scope=False, preflight_path=None, refresh_from_version=None):
    started = time.monotonic()
    initial_changes = connection.total_changes
    if refresh_from_version is not None and len(definitions) != 1:
        raise ValueError("Stale no-hit refresh is limited to one analyzer and a saved validation scope")
    expected_ids = (validation_scope_ids if validation_scope else heavy_test_game_ids)(database_path.parent)
    if sorted(game_ids) != expected_ids:
        raise ValueError("Heavy rollout is restricted to the exact saved validation scope")
    placeholders = ",".join("?" for _ in game_ids)
    scope_moves = {r[0] for r in connection.execute(
        f"SELECT m.move_id FROM moves m JOIN games g ON g.game_id=m.game_id "
        f"WHERE m.game_id IN ({placeholders}) AND m.is_user_move=1 AND COALESCE(g.source,'')<>'dev'",game_ids)}
    if len(moves) != len(scope_moves) or {r["move_id"] for r in moves} != scope_moves:
        raise ValueError("Heavy input moves do not match the selected real-game scope")
    connection.execute("PRAGMA foreign_keys=ON")
    integrity_check(connection)
    before = protected_snapshot(connection)
    before_coverage = coverage_rows(connection)
    before_candidates = {r["candidate_id"]:dict(r) for r in connection.execute("SELECT * FROM tactic_candidates")}
    before_sequence = [tuple(r) for r in connection.execute("SELECT * FROM sqlite_sequence ORDER BY name")]
    candidate_ids_in_scope = [r[0] for r in connection.execute(
        f"SELECT c.candidate_id FROM tactic_candidates c JOIN moves m ON m.move_id=c.move_id "
        f"WHERE m.game_id IN ({placeholders}) ORDER BY c.candidate_id",game_ids)]
    report = {"games":len(game_ids),"game_ids":game_ids,"moves":len(moves),"analyzers":{},"errors":[],"new_candidate_ids":[],"updated_candidate_ids":[],
              "candidate_ids_in_scope_before":candidate_ids_in_scope,
              "analysis_types":[d.analysis_type for d in definitions],"candidate_audit_records":[]}
    report["refresh_from_version"] = refresh_from_version
    with ExitStack() as stack:
        engine = LazyScoutEngine(stack,database_path.parent)
        evidence = None
        if refresh_from_version is not None:
            negatives = []
            plan = plan_stale_no_hits(connection,definitions,moves,decide,refresh_from_version)
        else:
            scratch = stack.enter_context(closing(sqlite3.connect(":memory:")))
            evidence = DryRunEvidence(connection,engine,scratch)
            negatives, plan = plan_negatives(connection,definitions,moves,evidence,decide)
        report["planning_stages"] = plan["analyzers"]
        if "existing_evidence_preflight" in plan:
            report["existing_evidence_preflight"] = plan["existing_evidence_preflight"]
        report["scout_engine_cache"] = plan["engine_cache"]
        report["negative_checks_deferred"] = len(negatives)
        report["static_scout_negatives_written"] = 0
        report["protected_candidate_ids_in_scope"] = plan.get("protected_candidate_ids_in_scope", [])
        report["errors"].extend(plan["errors"])
        pending = plan["pending_heavy_checks"]
        report["pending_before"] = dict(Counter(p["analysis_type"] for p in pending))
        print("Controlled heavy queue:",json.dumps(report["pending_before"]),flush=True)
        if report["errors"]:
            report["aborted"] = True
            pending = []
        if pending:
            report["backup"] = str(create_backup(connection,database_path,"heavy_analysis"))
        else:
            report["backup"] = None
        preflight = {"games":len(game_ids),"game_ids":game_ids,"moves":len(moves),
                     "candidate_count":len(before_candidates),"training_attempt_count":before["training_attempts"]["count"],
                     "coverage_count":len(before_coverage),"candidate_ids_in_scope":candidate_ids_in_scope,
                     "existing_candidate_ids":sorted(before_candidates),"analysis_types":[d.analysis_type for d in definitions],
                     "pending_heavy_checks":pending,"pending_by_tactic":report["pending_before"],
                     "backup":report["backup"],"errors":report["errors"][:]}
        preflight.update(refresh_from_version=refresh_from_version,
                         protected_candidate_ids_in_scope=report["protected_candidate_ids_in_scope"],
                         candidate_ids_by_tactic={t:sorted(i for i,c in before_candidates.items() if c["tactic_type"]==t)
                                                 for t in sorted({c["tactic_type"] for c in before_candidates.values()})},
                         protected_table_snapshot=before, quick_check="ok", foreign_key_check="ok")
        if "existing_evidence_preflight" in plan:
            preflight["existing_evidence_preflight"] = plan["existing_evidence_preflight"]
        if preflight_path is not None:
            preflight_path.parent.mkdir(parents=True,exist_ok=True)
            preflight_path.write_text(json.dumps(preflight,indent=2)+"\n",encoding="utf-8")
            print(f"Pre-run audit: {preflight_path.resolve()}",flush=True)
        report["scout_cache_rows_saved"] = evidence.persist_scout_cache() if pending and evidence is not None else 0
        move_by_id = {r["move_id"]:r for r in moves}
        by_type = {d.analysis_type:d for d in definitions}
        allowed = {(p["move_id"],p["analysis_type"]) for p in pending}
        for definition in definitions:
            report["analyzers"][definition.analysis_type] = {
                "attempted":0,"candidate":0,"analyzed_no_hit":0,"error":0,"rejected":0,
                "cache_hits":0,"cache_misses":0,
            }
        for index, item in enumerate(pending,1):
            definition = by_type[item["analysis_type"]]
            row = move_by_id[item["move_id"]]
            counts = report["analyzers"][definition.analysis_type]
            cache_stats = Counter()
            result = dispatch_heavy(definition,connection,engine,row,cache_stats)
            counts["attempted"] += 1
            counts["cache_hits"] += cache_stats["hits"]
            counts["cache_misses"] += cache_stats["misses"]
            options = {"expected_no_hit_version":refresh_from_version} if refresh_from_version is not None else {}
            saved = save_heavy_result(connection,definition,row,result,allowed,decide,**options)
            counts[saved["state"]] += 1
            if saved["action"] == "candidate_created":
                report["new_candidate_ids"].append(saved["candidate_id"])
            elif saved["action"] in {"candidate_updated","candidate_reconciled"}:
                report["updated_candidate_ids"].append(saved["candidate_id"])
            if result.state == "candidate" and saved["action"] in {"candidate_created","candidate_updated"}:
                report["candidate_audit_records"].append({
                    "candidate_id":saved["candidate_id"],"analysis_type":definition.analysis_type,
                    "game_id":row["game_id"],"source":row["source"],"source_game_id":row["source_game_id"],
                    "move_id":row["move_id"],"move_number":row["move_number"],"color":row["color"],
                    "played_san":row["san_played"],"played_uci":row["uci_played"],
                    "solution_move_san":result.candidate["solution_move_san"],
                    "solution_move_uci":result.candidate["solution_move_uci"],
                    "proof_continuation":result.candidate["solution_line"],
                    "metadata":json.loads(result.candidate.get("metadata_json") or "{}"),
                    "opportunity": opportunity_to_dict(read_candidate_opportunity(connection,saved["candidate_id"]).opportunity)
                                   if result.opportunity is not None else None,
                })
            if result.state == "error":
                report["errors"].append({**item,**result.details})
            print(f"Heavy {index}/{len(pending)}: {definition.analysis_type} move {row['move_id']} -> {result.state}",flush=True)
    after = protected_snapshot(connection)
    if {k:v for k,v in before.items() if k != "tactic_candidates"} != {k:v for k,v in after.items() if k != "tactic_candidates"}:
        raise RuntimeError("Data outside candidate/coverage/cache services changed")
    final_coverage = coverage_rows(connection)
    final_candidates = {r["candidate_id"]:dict(r) for r in connection.execute("SELECT * FROM tactic_candidates")}
    allowed = {(p["move_id"],p["analysis_type"]) for p in pending}
    if {k:v for k,v in before_coverage.items() if k not in allowed} != {k:v for k,v in final_coverage.items() if k not in allowed}:
        raise RuntimeError("Coverage outside the authorized queue changed")
    for candidate_id, candidate in before_candidates.items():
        if candidate_id not in final_candidates:
            raise RuntimeError("Existing candidate ID removed")
        if (candidate["move_id"],candidate["tactic_type"]) not in allowed and final_candidates[candidate_id] != candidate:
            raise RuntimeError("Candidate outside the authorized queue changed")
        if refresh_from_version is not None and final_candidates[candidate_id] != candidate:
            raise RuntimeError("No-hit refresh modified an existing candidate")
    duplicates = connection.execute("SELECT move_id,tactic_type,COUNT(*) FROM tactic_candidates GROUP BY move_id,tactic_type HAVING COUNT(*)>1").fetchall()
    if duplicates:
        raise RuntimeError("Duplicate canonical candidates detected")
    integrity_check(connection)
    report.update(candidate_counts={"before":len(before_candidates),"after":len(final_candidates)},
                  training_attempt_counts={"before":before["training_attempts"]["count"],"after":after["training_attempts"]["count"]},
                  coverage_counts={"before":len(before_coverage),"after":len(final_coverage)},
                  existing_candidate_ids_preserved=len(before_candidates),
                  all_existing_candidates_unchanged=all(final_candidates.get(i)==c for i,c in before_candidates.items()),
                  outside_scope_unchanged=True,duplicates=0,
                  coverage_unchanged=before_coverage==final_coverage,
                  candidates_unchanged=before_candidates==final_candidates,
                  sequences_unchanged=before_sequence==[tuple(r) for r in connection.execute("SELECT * FROM sqlite_sequence ORDER BY name")],
                  database_row_changes=connection.total_changes-initial_changes,
                  candidate_ids_in_scope_preserved=all(i in final_candidates for i in candidate_ids_in_scope),
                  elapsed_seconds=round(time.monotonic()-started,2),
                  quick_check="ok",foreign_key_check="ok")
    print("Heavy result:",json.dumps(report,indent=2),flush=True)
    return report
