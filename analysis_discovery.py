"""Explicit saved-cohort orchestration; registry specialists own tactic calculations."""
from collections import Counter
from contextlib import ExitStack
from types import SimpleNamespace
from pathlib import Path
import hashlib,json,sqlite3,time
from analysis_crawler import load_user_moves,coverage_decision
from analysis_planner import plan_negatives
from analysis_engine import LazyScoutEngine,DryRunEvidence
from analysis_safety import create_backup,integrity_check
from heavy_adapters import dispatch_heavy
from heavy_repository import save_heavy_result
from negative_coverage import apply_negatives
from candidate_line_engine import CandidateLineGenerator
from candidate_line_repository import CandidateLineRepository,insert_only_authorizer
from candidate_line_service import CandidateLineService
from candidate_lines import to_data
from discovery_registry import DISCOVERY_ANALYZERS
from discovery_scope import validate_scope
from discovery_safety import snapshot,verify


def run_discovery(database_path,scope_path,report_path):
    root=database_path.parent;started=time.monotonic()
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    scope=json.loads(scope_path.read_text(encoding="utf-8"))
    definition,profile,target=DISCOVERY_ANALYZERS[scope["experiment"]]()
    if sha(root/scope["first_cohort_artifact"])!=scope["first_cohort_sha256"]: raise ValueError("Original scope provenance changed")
    first=json.loads((root/scope["first_cohort_artifact"]).read_text())["game_ids"]
    if set(first)&set(scope["game_ids"]): raise ValueError("Cohorts overlap")
    outputs=report_path.parent
    prefix=report_path.stem.removesuffix("_summary")
    sources={p.name:sha(p) for p in root.glob("*.py")}
    with ExitStack() as stack:
        db=sqlite3.connect(database_path.as_uri()+"?mode=rw",uri=True);stack.callback(db.close);db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        rows=[dict(r) for r in load_user_moves(db,scope["game_ids"])]
        validate_scope(scope,rows,target)
        before=snapshot(db);before_sha=sha(database_path);before_size=database_path.stat().st_size
        backup=create_backup(db,database_path,"fork_second_500")
        frozen={"profile":to_data(profile),"target_identity":target,"screener_version":definition.screener_version,
                "scout_version":definition.scout_version,"scout_config":json.loads(definition.scout_config()),
                "analyzer_version":definition.analyzer_version,"source_hashes":sources}
        counts={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in
                ("games","moves","tactic_candidates","training_attempts","analysis_coverage","engine_position_cache","engine_candidate_line_cache")}
        preflight={"counts":counts,"existing_candidate_ids":list(before["candidates"]),"scope":scope,"frozen":frozen,
                   "database_sha256":before_sha,"database_bytes":before_size,"backup":str(backup),"backup_sha256":sha(backup),
                   "quick_check":"ok","foreign_key_check":[],
                   "coverage_in_scope":[v for (mid,tactic),v in before["coverage"].items() if tactic==definition.analysis_type and mid in {r["move_id"] for r in rows}]}
        (outputs/(prefix+"_before.json")).write_text(json.dumps(preflight,indent=2),encoding="utf-8")
        engine=LazyScoutEngine(stack,root)
        scratch=sqlite3.connect(":memory:");stack.callback(scratch.close)
        class PlanningEvidence(DryRunEvidence):
            def position(self,fen):
                result=super().position(fen)
                if len(self.positions)%100==0:
                    progress={"phase":"scout","unique_positions":len(self.positions),"cache":dict(self.stats),"elapsed_seconds":time.monotonic()-started}
                    (outputs/(prefix+"_progress.json")).write_text(json.dumps(progress,indent=2),encoding="utf-8")
                    print(json.dumps(progress),flush=True)
                return result
        evidence=PlanningEvidence(db,engine,scratch)
        print("Planning saved scope: static and scout",flush=True)
        negatives,plan=plan_negatives(db,[definition],rows,evidence,coverage_decision)
        (outputs/(prefix+"_plan.json")).write_text(json.dumps(plan,indent=2),encoding="utf-8")
        if plan["errors"]: raise RuntimeError("Planning errors; no planned coverage writes applied")
        promoted=evidence.persist_scout_cache()
        negative_writes=dict(apply_negatives(db,negatives,scope["game_ids"],{definition.analysis_type}))
        cache=sqlite3.connect(database_path.as_uri()+"?mode=rw",uri=True,isolation_level=None);stack.callback(cache.close)
        cache.set_authorizer(insert_only_authorizer)
        repository=CandidateLineRepository(cache)
        breadth=CandidateLineService(CandidateLineGenerator(engine),write_store=repository)
        verification=CandidateLineService(CandidateLineGenerator(engine),write_store=repository)
        services=SimpleNamespace(breadth=breadth,verification=verification)
        pending=plan["pending_heavy_checks"];by_move={r["move_id"]:r for r in rows}
        allowed={(r["move_id"],definition.analysis_type) for r in rows}
        records=[];states=Counter();proposal_states=Counter()
        output=stack.enter_context((outputs/(prefix+"_results.jsonl")).open("w",encoding="utf-8"))
        print(f"Heavy queue: {len(pending)}",flush=True)
        for index,item in enumerate(pending,1):
            row=by_move[item["move_id"]];tick=time.monotonic();cost_b=breadth.stats.copy();cost_v=verification.stats.copy()
            result=dispatch_heavy(definition,db,engine,row,Counter(),position_service=services)
            saved=save_heavy_result(db,definition,row,result,allowed,coverage_decision,preserve_existing=True)
            states[result.state]+=1
            for proposal in result.details.get("proposals",[]): proposal_states[proposal["result"]["details"]["classification"]]+=1
            record={"index":index,"row":row,"state":result.state,"saved":saved,"details":result.details,
                    "candidate":result.candidate,"opportunity":to_data(result.opportunity),
                    "breadth_cost":dict(breadth.stats-cost_b),"verification_cost":dict(verification.stats-cost_v),"elapsed_seconds":time.monotonic()-tick}
            records.append(record);output.write(json.dumps(record)+"\n");output.flush()
            progress={"completed":index,"total":len(pending),"states":dict(states),"proposal_states":dict(proposal_states),
                      "breadth":dict(breadth.stats),"verification":dict(verification.stats),"elapsed_seconds":time.monotonic()-started}
            (outputs/(prefix+"_progress.json")).write_text(json.dumps(progress,indent=2),encoding="utf-8")
            print(json.dumps(progress),flush=True)
            if "error_type" in result.details: raise RuntimeError("Operational heavy error; stop for inspection")
        first_cost={"breadth":dict(breadth.stats),"verification":dict(verification.stats)}
        first_elapsed=time.monotonic()-started
        safety=verify(db,before,allowed)
        post_first_sha=sha(database_path);changes=db.total_changes;cache_changes=cache.total_changes
        class NoEngine:
            def generate(self,*args,**kwargs): raise AssertionError("Identical rerun attempted an unnecessary engine search")
        breadth.generator=NoEngine();verification.generator=NoEngine()
        rerun_scratch=sqlite3.connect(":memory:");stack.callback(rerun_scratch.close)
        class NoScoutEngine:
            def analyse(self,*args,**kwargs): raise AssertionError("Identical rerun attempted an unnecessary scout search")
        rerun_evidence=DryRunEvidence(db,NoScoutEngine(),rerun_scratch)
        rerun_negatives,rerun_plan=plan_negatives(db,[definition],rows,rerun_evidence,coverage_decision)
        rerun_writes=apply_negatives(db,rerun_negatives,scope["game_ids"],{definition.analysis_type})
        for item in rerun_plan["pending_heavy_checks"]:
            row=by_move[item["move_id"]]
            result=dispatch_heavy(definition,db,engine,row,Counter(),position_service=services)
            if "error_type" in result.details: raise RuntimeError(result.details)
            saved=save_heavy_result(db,definition,row,result,allowed,coverage_decision,preserve_existing=True)
            if saved["action"]!="unchanged": raise RuntimeError("Rerun changed heavy result")
        assert db.total_changes==changes and cache.total_changes==cache_changes
        assert sha(database_path)==post_first_sha
        assert sources=={p.name:sha(p) for p in root.glob("*.py")}
        final=verify(db,before,allowed)
        summary={"scope":scope,"frozen":frozen,"planning":plan,"negative_writes":negative_writes,"scout_cache_rows_inserted":promoted,
                 "heavy_checks":len(pending),"move_states":dict(states),"proposal_classifications":dict(proposal_states),"first_cost":first_cost,
                 "first_elapsed_seconds":first_elapsed,"total_elapsed_seconds":time.monotonic()-started,"safety":final,
                 "counts_before":counts,"database_growth_bytes":database_path.stat().st_size-before_size,
                 "database_sha256_before":before_sha,"database_sha256_after":sha(database_path),
                 "rerun":{"plan":rerun_plan,"negative_writes":dict(rerun_writes),"database_writes":db.total_changes-changes,
                     "cache_writes":cache.total_changes-cache_changes,"byte_identical":True,
                     "breadth":dict(breadth.stats-Counter(first_cost["breadth"])),"verification":dict(verification.stats-Counter(first_cost["verification"]))}}
        report_path.write_text(json.dumps(summary,indent=2),encoding="utf-8")
        print("Completed saved-cohort run, identical rerun, and safety audit",flush=True)
        return summary
