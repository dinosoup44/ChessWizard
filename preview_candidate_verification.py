"""Read-only existing-candidate preview. Deliberately has no apply/write mode."""
import argparse
from collections import Counter
from contextlib import ExitStack,closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import chess
from analysis_engine import DryRunPositionAnalysisService,LazyScoutEngine
from analysis_safety import create_backup,integrity_check
from candidate_verification import existing_candidates,verify_candidates
from candidate_verification_registry import CANDIDATE_VERIFIERS
from tactical_opportunities import opportunity_to_dict
from tactical_proof import verify_bounded_line
from analyze_forks_v3 import PIECE_VALUES,POLICY
from board_analysis import attacked_pieces,material_balance
from tactical_target_proof import trace_target_settlement
from engine_cache import score_for_color
from feedback import FeedbackContextBuilder,FeedbackGenerator


def audit_reply_choices(row,positions,reply_names):
    board=chess.Board(row["fen_before"]);color=board.turn
    fork=board.parse_uci(row["solution_move_uci"]);board.push(fork)
    before_raw=positions.position(board.fen(),POLICY.profile)
    targets=attacked_pieces(board,fork.to_square,target_color=not color,
                            piece_types=(chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN,chess.KING))
    ranking=[]
    for reply in list(board.legal_moves):
        child=board.copy(stack=False);name=board.san(reply);child.push(reply)
        score=score_for_color(positions.position(child.fen(),POLICY.profile),color)
        ordering=score["score_cp"] if score["score_type"]=="cp" else (100000-abs(score["mate"]) if score["mate"]>0 else -100000+abs(score["mate"]))
        ranking.append({"reply":name,"uci":reply.uci(),"player_evaluation":score,"ordering":ordering})
    ranking.sort(key=lambda r:(r["ordering"],r["uci"]))
    for i,r in enumerate(ranking,1):r["rank_by_child_evaluation"]=i
    branches=[]
    for name in reply_names:
        reply=board.parse_san(name);child=board.copy(stack=False);child.push(reply)
        child_raw=positions.position(child.fen(),POLICY.profile)
        def forced(fen):
            if fen==board.fen():
                return {**before_raw,"principal_variation":name+" "+(child_raw.get("principal_variation") or "")}
            return positions.position(fen,POLICY.profile)
        proof=verify_bounded_line(board,color,forced,PIECE_VALUES,POLICY.window)
        trace=trace_target_settlement(board,fork.to_square,targets,proof,PIECE_VALUES)
        alternatives=[]
        for response in child.legal_moves:
            if response.to_square==reply.to_square or (response.from_square==fork.to_square and response.to_square in {t.square for t in targets}):
                next_board=child.copy(stack=False);san=child.san(response);next_board.push(response)
                raw=positions.position(next_board.fen(),POLICY.profile)
                alternatives.append({"move":san,"uci":response.uci(),"player_evaluation":score_for_color(raw,color),"best_reply":raw.get("principal_variation")})
        branches.append({"reply":name,"best_player_response":child_raw.get("best_move_san"),
            "reply_evaluation":score_for_color(child_raw,color),"state":proof.state,
            "line":" ".join([row["solution_move_san"],*(s.san for s in proof.steps)]),
            "material_initial_cp":material_balance(chess.Board(row["fen_before"]),color,PIECE_VALUES),
            "material_final_cp":material_balance(chess.Board(proof.final_fen),color,PIECE_VALUES),
            "final_evaluation":score_for_color(positions.position(proof.final_fen,POLICY.profile),color),
            "trace":asdict(trace),"target_capture_or_recapture_alternatives":alternatives})
    return {"candidate_id":row["candidate_id"],"fen_before":row["fen_before"],"stored_line":row["solution_line"],
            "ranking_method":"All legal opponent replies evaluated individually with single-PV depth18 child searches; diagnostic ranking, not native MultiPV or an exhaustive proof.",
            "cached_root_best_reply":before_raw.get("best_move_san"),"ranking":ranking,"branches":branches}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis",choices=tuple(CANDIDATE_VERIFIERS),required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent;db=root/"merlin.db";out=root/"reports"
    before_hash=hashlib.sha256(db.read_bytes()).hexdigest();started=time.monotonic()
    with ExitStack() as stack:
        c=stack.enter_context(closing(sqlite3.connect(db.as_uri()+"?mode=ro",uri=True)))
        c.row_factory=sqlite3.Row;c.execute("PRAGMA query_only=ON");integrity_check(c)
        backup=create_backup(c,db,purpose="fork_v3_readonly_preview")
        rows=existing_candidates(c,args.analysis)
        coverage=[dict(r) for r in c.execute("SELECT * FROM analysis_coverage WHERE analysis_type=?",(args.analysis,))]
        links=[dict(r) for r in c.execute("SELECT * FROM training_attempts WHERE candidate_id IN (SELECT candidate_id FROM tactic_candidates WHERE tactic_type=?)",(args.analysis,))]
        counts={t:c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("tactic_candidates","training_attempts","analysis_coverage","engine_position_cache")}
        inventory={"database_sha256":before_hash,"backup":str(backup),"counts":counts,"candidates":rows,"coverage":coverage,"training_links":links}
        (out/"fork_v3_before.json").write_text(json.dumps(inventory,indent=2),encoding="utf-8")
        keys=Counter((r["move_id"],r["tactic_type"]) for r in rows)
        rejected_coverage={r["move_id"] for r in coverage if r["coverage_status"]=="rejected"}
        eligible=[r for r in rows if r["candidate_status"]=="candidate" and str(r["detector_version"])=="2" and keys[(r["move_id"],r["tactic_type"])]==1 and r["move_id"] not in rejected_coverage]
        stats=Counter();scratch=stack.enter_context(closing(sqlite3.connect(":memory:")))
        positions=DryRunPositionAnalysisService(c,LazyScoutEngine(stack,root),stats,scratch)
        manual=next((r for r in eligible if r["solution_line"]=="Qxb7 Bxf4 Qxc6"),None)
        if manual:
            print(f"Auditing requested Qxb7 candidate {manual['candidate_id']} first",flush=True)
            audit=audit_reply_choices(manual,positions,("Bxf1","Bxf4"))
            (out/"fork_v3_manual_qxb7.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
            print("Manual Qxb7 branch audit saved",flush=True)
        totals=Counter();saved=[];last_print=time.monotonic()
        with (out/"fork_v3_results.jsonl").open("w",encoding="utf-8") as log:
            def record(row,result,completed,total):
                nonlocal last_print
                classification=result.details.get("classification",result.state)
                totals[classification]+=1
                record={"candidate_id":row["candidate_id"],"game_id":row["game_id"],"source_game_id":row["source_game_id"],
                        "move_number":row["move_number"],"color":row["color"],"state":result.state,"details":result.details,
                        "candidate":result.candidate,"opportunity":opportunity_to_dict(result.opportunity) if result.opportunity else None}
                if result.opportunity:
                    record["feedback"]=asdict(FeedbackGenerator().generate(FeedbackContextBuilder().build({**row,**result.candidate},result.opportunity)))
                log.write(json.dumps(record)+"\n");log.flush();saved.append(record)
                progress={"completed":completed,"total":total,"outcomes":dict(totals),"cache":dict(stats),"elapsed_seconds":round(time.monotonic()-started,2)}
                (out/"fork_v3_progress.json").write_text(json.dumps(progress,indent=2),encoding="utf-8")
                if completed%10==0 or time.monotonic()-last_print>30 or completed==total:
                    print(json.dumps(progress),flush=True);last_print=time.monotonic()
            verify_candidates(eligible,CANDIDATE_VERIFIERS[args.analysis],positions,record)
        integrity_check(c)
        after_counts={t:c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in counts}
        assert counts==after_counts and c.total_changes==0
        assert existing_candidates(c,args.analysis)==rows
        assert [dict(r) for r in c.execute("SELECT * FROM analysis_coverage WHERE analysis_type=?",(args.analysis,))]==coverage
        after_hash=hashlib.sha256(db.read_bytes()).hexdigest();assert before_hash==after_hash
        summary={"total_fork_rows":len(rows),"active_considered":sum(r["candidate_status"]=="candidate" for r in rows),
            "eligible_v2_candidates":len(eligible),"protected_rows":len(rows)-len(eligible),"outcomes":dict(totals),
            "realizable_differs":sum(bool(r["details"].get("geometric_vs_realizable_differ")) for r in saved),
            "best_counterplay_changed":sum(bool(r["details"].get("best_response_changed")) for r in saved),
            "cache":dict(stats),"counts_before":counts,"counts_after":after_counts,"candidate_ids_preserved":len(rows),
            "database_sha256_before":before_hash,"database_sha256_after":after_hash,"live_database_writes":0,
            "elapsed_seconds":round(time.monotonic()-started,2),"quick_check":"ok","foreign_key_check":[],"backup":str(backup)}
        (out/"fork_v3_preview.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__":main()
