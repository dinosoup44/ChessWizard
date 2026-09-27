"""Reproducible dated real-game cohorts with coverage-aware eligibility."""
from collections import Counter
from datetime import datetime
import hashlib
import json
import re
import chess
from analysis_crawler import coverage_decision


def build_scope(connection, definition, target_identity, first_ids, count=500):
    """Exclude the original cohort and fully current workflows before chronological selection."""
    games=[dict(r) for r in connection.execute("SELECT game_id,source,source_game_id,played_at,account_id,variant,raw_pgn FROM games")]
    moves={}; coverage={}
    for r in connection.execute("SELECT move_id,game_id,is_user_move,fen_before,ply_number FROM moves ORDER BY game_id,ply_number"):
        moves.setdefault(r["game_id"],[]).append(dict(r))
    for r in connection.execute("SELECT * FROM analysis_coverage WHERE analysis_type=?",(definition.analysis_type,)):
        coverage[r["move_id"]]=dict(r)
    excluded=Counter(); eligible=[]
    for game in games:
        reason=None; rows=moves.get(game["game_id"],[]); users=[r for r in rows if r["is_user_move"]]
        if game["source"] not in {"chesscom","lichess"} or game["account_id"] is None: reason="not_real_import"
        elif game["game_id"] in first_ids: reason="first_cohort"
        elif not users: reason="no_user_moves"
        elif not game["raw_pgn"] or rows[0]["fen_before"]!=chess.STARTING_FEN: reason="nonstandard_or_setup_fixture"
        elif game["variant"] not in (None,"","standard","Standard","chess"): reason="variant"
        if reason:
            excluded[reason]+=1; continue
        def current(move):
            cov=coverage.get(move["move_id"])
            if coverage_decision(definition,cov)!="current": return False
            if cov["coverage_status"] in {"screened_out","scouted_out"}: return True
            return json.loads(cov.get("details_json") or "{}").get("discovery_identity")==target_identity
        if all(current(m) for m in users):
            excluded["fully_current_target_workflow"]+=1; continue
        date=game["played_at"] or ""
        time_match=re.search(r'\[UTCTime "([0-9:]+)"\]',game["raw_pgn"])
        try:
            stamp=datetime.fromisoformat(date.replace(".","-").replace("Z","+00:00"))
            if time_match and len(date)==10: stamp=datetime.fromisoformat(date.replace(".","-")+"T"+time_match.group(1))
        except ValueError:
            excluded["missing_or_invalid_date"]+=1; continue
        entry={k:v for k,v in game.items() if k not in {"raw_pgn","account_id","variant"}}
        entry.update(sort_date=stamp.isoformat(),user_moves=len(users),total_plies=len(rows),
                     target_current_moves=sum(current(m) for m in users),
                     fork_coverage=dict(Counter(coverage[m["move_id"]]["analyzer_version"]+":"+coverage[m["move_id"]]["coverage_status"] for m in users if m["move_id"] in coverage)))
        eligible.append(entry)
    eligible.sort(key=lambda g:(g["sort_date"],g["game_id"]),reverse=True)
    if len(eligible)<count: raise ValueError(f"Only {len(eligible)} eligible games; need {count}. Exclusions: {dict(excluded)}")
    selected=eligible[:count]
    ids=[g["game_id"] for g in selected]
    return {"games":count,"game_ids":ids,"records":selected,"target_identity":target_identity,
            "analysis_type":definition.analysis_type,"analyzer_version":definition.analyzer_version,
            "user_moves":sum(g["user_moves"] for g in selected),"total_plies":sum(g["total_plies"] for g in selected),
            "overlap":len(set(ids)&set(first_ids)),"exclusions":dict(excluded),"eligible_not_selected":len(eligible)-count,
            "newest":selected[0]["sort_date"],"oldest":selected[-1]["sort_date"]}


def validate_scope(scope, rows, target_identity):
    if scope["games"]!=500 or len(scope["game_ids"])!=500 or len(set(scope["game_ids"]))!=500 or scope["overlap"]:
        raise ValueError("Expected exactly 500 distinct nonoverlapping saved games")
    if scope["target_identity"]!=target_identity: raise ValueError("Frozen discovery settings changed")
    if len(rows)!=scope["user_moves"] or {r["game_id"] for r in rows}!=set(scope["game_ids"]):
        raise ValueError("Saved scope/move population changed")
