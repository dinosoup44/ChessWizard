from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
import ast
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch
import chess

from analysis_backbone import AnalysisBackbone
from analysis_settings import load_profile, AnalysisProfile
from analysis_states import EvidenceState, approval_state, escalation_state
from candidate_line_service import CandidateLineService
from candidate_line_repository import CandidateLineRepository
from candidate_line_diagnostics import CandidateLineDiagnosticsService
from candidate_verification_result import CandidateVerificationResult, verification_result
from analysis_results import HeavyResult
from candidate_lines import LineScore, to_data
from proof_escalation import ProofEscalationResult
from settlement_evidence import settlement_evidence
from tactical_proof import BoundedProof, ProofWindow
from migrate_candidate_line_cache import migrate
from test_proof_escalation import PVService, pv_set, request
from test_fork_multiline import FixtureService
import test_forks_v3 as fixtures


class BackboneTests(unittest.TestCase):
    def test_one_and_three_lines_and_no_implicit_escalation(self):
        for preset, count in (("quick",1),("normal",3)):
            service = FixtureService(fixtures.candidate(), [("Nc7+",400),("Kf1",375),("Kd1",350)])
            deep = Mock()
            core = AnalysisBackbone(service,load_profile(preset),verification_service=deep)
            approved = core.request(service.row["fen_before"])
            self.assertEqual(len(approved.lines),count)
            self.assertEqual(approval_state(approved),EvidenceState.APPROVED)
            weighted = core.weigh(approved)
            self.assertEqual(len(weighted.lines),count)
            self.assertIn("settlement_quality",weighted.lines[0].unknown_components)
            self.assertEqual(weighted.evidence_provenance["engine_identity"],approved.source.engine_identity)
            self.assertEqual(core.escalation.branches_escalated,0)
            deep.candidate_lines.assert_not_called()
            with self.assertRaises(TypeError): core.weigh(approved.source)

    def test_incomplete_forced_and_losing_best_handoff(self):
        incomplete = AnalysisBackbone(PVService(complete=False)).request(chess.STARTING_FEN)
        self.assertEqual(approval_state(incomplete),EvidenceState.INCOMPLETE)
        self.assertFalse(incomplete.lines)
        core = AnalysisBackbone(PVService(score=LineScore(mate_score=-3)))
        forced = core.request(chess.STARTING_FEN)
        self.assertEqual(approval_state(forced),EvidenceState.FORCED_DETERIORATION)
        self.assertTrue(core.weigh(forced).lines)
        self.assertTrue(all(not decision.normal_accepted for decision in forced.decisions))
        losing = AnalysisBackbone(PVService(score=LineScore(-700))).request(chess.STARTING_FEN)
        self.assertEqual(approval_state(losing),EvidenceState.APPROVED)
        self.assertEqual(losing.lines[0].score.score_cp,-700)

    def test_gate_rejected_move_is_not_missing_evidence(self):
        raw = FixtureService(fixtures.candidate(),[("Kf1",800),("Nc7+",0)])
        core = AnalysisBackbone(raw)
        admission = core.admit(raw.row["fen_before"],"d5c7")
        self.assertEqual(approval_state(admission.approved,"d5c7"),EvidenceState.REJECTED_BY_QUALITY_GATE)
        self.assertEqual(approval_state(admission.approved,"e1d1"),EvidenceState.INCOMPLETE)

    def test_provenance_policy_changes_reuse_raw_cache(self):
        with closing(sqlite3.connect(":memory:")) as db:
            migrate(db)
            generator=Mock(); generator.generate.side_effect=pv_set
            service=CandidateLineService(generator,write_store=CandidateLineRepository(db))
            base=AnalysisProfile()
            profiles=(base,replace(base,scale=replace(base.scale,base_interest=50)),
                replace(base,quality_gate=replace(base.quality_gate,absolute_tolerance_cp=90)))
            identities=[]
            for profile in profiles:
                core=AnalysisBackbone(service,profile)
                approved=core.request(chess.STARTING_FEN); core.weigh(approved)
                provenance=core.provenance("fixture","1",interpretation_policy={"attribution":1})
                identities.append(provenance.currentness_identity)
                self.assertEqual(provenance,core.provenance("fixture","1",interpretation_policy={"attribution":1}))
                self.assertNotEqual(provenance.currentness_identity,core.provenance("fixture","2",interpretation_policy={"attribution":1}).currentness_identity)
            self.assertEqual(len(set(identities)),3)
            self.assertEqual(generator.generate.call_count,1)
            self.assertEqual(service.stats["cache_hits"],2)

    def test_currentness_includes_supplied_continuation(self):
        from continuation_quality import ContinuationEvidence,line_identity
        core=AnalysisBackbone(PVService())
        approved=core.request(chess.STARTING_FEN)
        core.weigh(approved)
        first=core.provenance("fixture","1")
        line=approved.lines[0]
        evidence=ContinuationEvidence(line_identity(chess.STARTING_FEN,line),line.engine_identity,"fixture",settled=True)
        core.weigh(approved,{line.move_uci:evidence})
        self.assertNotEqual(first.currentness_identity,core.provenance("fixture","1").currentness_identity)
        self.assertEqual(first.breadth_engine_identity,core.provenance("fixture","1").breadth_engine_identity)

    def test_restricted_and_line_count_requests_do_not_collide(self):
        from candidate_line_request import request_identity
        profile=AnalysisProfile()
        self.assertNotEqual(request_identity(profile.generator),request_identity(profile.generator,("e2e4",)))
        self.assertNotEqual(request_identity(profile.generator),request_identity(replace(profile.generator,candidate_line_count=1)))
        self.assertNotEqual(request_identity(profile.generator),request_identity(replace(profile.generator,engine=replace(profile.generator.engine,depth=18))))

    def test_lazy_selective_dispatch_rechecks_after_each_result(self):
        core=AnalysisBackbone(PVService(),load_profile("normal_escalation"))
        chosen=[]
        def selections():
            yield "first",request()
            if not chosen:
                yield "unnecessary",request()
        for key,result in core.escalation.escalate_selected(selections(),fixtures.PIECE_VALUES):
            self.assertEqual(result.status,"complete");chosen.append(key)
        self.assertEqual(chosen,["first"])
        self.assertEqual(core.escalation.branches_escalated,1)
        skipped=core.escalation.escalate(request(observed="stable"),fixtures.PIECE_VALUES)
        self.assertEqual(skipped.status,"not_needed")
        self.assertIsNone(escalation_state(skipped))

    def test_deep_execution_error_is_structured_and_never_ambiguity(self):
        failing=Mock();failing.candidate_lines.side_effect=RuntimeError("engine unavailable")
        core=AnalysisBackbone(PVService(),load_profile("normal_escalation"),verification_service=failing)
        result=core.escalation.escalate(request(),fixtures.PIECE_VALUES)
        self.assertEqual(result.status,"error")
        self.assertEqual(escalation_state(result),EvidenceState.EXECUTION_ERROR)
        self.assertIn("engine unavailable",result.reason)

    def test_fork_boundary_preserves_deep_execution_error(self):
        from candidate_verification import verify_candidates
        from candidate_verification_registry import escalating_fork_verifier
        from test_fork_multiline import selected_two_ply_proof
        row=fixtures.candidate("r3k3/7p/8/3N4/8/8/P7/4K3 w - - 0 1")
        raw=FixtureService(row)
        deep=Mock();deep.candidate_lines.side_effect=RuntimeError("engine unavailable")
        def unsettled(*args): return replace(selected_two_ply_proof(*args),state="unsettled")
        with patch("analyze_forks_v3_multiline.verify_bounded_line",side_effect=unsettled):
            result=verify_candidates([row],escalating_fork_verifier(load_profile("normal_escalation"),deep),raw)[0][1]
        self.assertEqual(result.state,"error")
        self.assertEqual(result.details["classification"],"error")
        self.assertIn("engine unavailable",result.details["message"])

    def test_settings_schema_is_frontend_ready_and_alias_compatible(self):
        schema={item.setting_id:item.to_schema() for item in load_profile("normal_escalation").schema()}
        json.dumps(schema)
        required={"setting_id","label","type","default","minimum","maximum","options","description","level","affects_raw_cache_identity","affects_result_currentness"}
        self.assertTrue(all(required<=set(value) for value in schema.values()))
        for key in ("generator.candidate_line_count","generator.engine.depth","escalation.verification.engine.depth"):
            self.assertTrue(schema[key]["affects_raw_cache_identity"])
        for key in ("quality_gate.absolute_tolerance_cp","scale.weights.material_payoff","escalation.max_requests_per_candidate"):
            self.assertFalse(schema[key]["affects_raw_cache_identity"])
            self.assertTrue(schema[key]["affects_result_currentness"])


class SettlementAndStateTests(unittest.TestCase):
    def test_stable_legal_material_and_profile_evidence(self):
        core=AnalysisBackbone(PVService(),load_profile("normal_escalation"))
        result=core.escalation.escalate(request(),fixtures.PIECE_VALUES)
        evidence=settlement_evidence(request().after_tactic_fen,"white",result.proof,
            profile_identity=result.profile_identity,evidence_requests=result.request_identities)
        self.assertTrue(evidence.settled)
        self.assertEqual(evidence.state,EvidenceState.PROOF_STABLE)
        self.assertEqual(evidence.final_evaluation.score_pov,"white")
        self.assertEqual(evidence.observed_material_change_cp,evidence.material_after_cp-evidence.material_before_cp)
        self.assertEqual(evidence.branch_length,len(result.proof.steps))
        damaged=replace(result.proof,steps=(replace(result.proof.steps[0],material_cp=999),*result.proof.steps[1:]))
        with self.assertRaises(ValueError): settlement_evidence(request().after_tactic_fen,"white",damaged,profile_identity="test")
        with self.assertRaises(ValueError): settlement_evidence(request().after_tactic_fen,"white",object(),profile_identity="test")

    def test_deferred_mate_budget_and_operational_error_states(self):
        for status,state in (("budget_exhausted",EvidenceState.PROOF_UNSETTLED),("incomplete",EvidenceState.INCOMPLETE),
                             ("deferred",EvidenceState.PROOF_DEFERRED),("error",EvidenceState.EXECUTION_ERROR)):
            self.assertEqual(escalation_state(ProofEscalationResult(status,"fixture")),state)
        core=AnalysisBackbone(PVService(score=LineScore(mate_score=-2)),load_profile("normal_escalation"))
        result=core.escalation.escalate(request(),fixtures.PIECE_VALUES)
        evidence=settlement_evidence(request().after_tactic_fen,"white",result.proof,profile_identity=result.profile_identity)
        self.assertFalse(evidence.settled);self.assertEqual(evidence.mate_winner,"black")
        legacy=HeavyResult("error",details={"classification":"ambiguous"})
        converted=verification_result(legacy)
        self.assertEqual(converted.state,"ambiguous");self.assertEqual(converted.classification,"ambiguous")
        self.assertEqual(verification_result(HeavyResult("error")).classification,"error")
        with self.assertRaises(ValueError): CandidateVerificationResult("error",details={"classification":"verified"}).classification


class CacheDiagnosticsTests(unittest.TestCase):
    def test_missing_empty_and_populated_read_only_diagnostics(self):
        with closing(sqlite3.connect(":memory:")) as db:
            diagnostics=CandidateLineDiagnosticsService(db)
            self.assertEqual(diagnostics.inspect().health,"not_installed")
            migrate(db)
            self.assertEqual(diagnostics.inspect().row_count,0)
            repository=CandidateLineRepository(db)
            value=pv_set(chess.STARTING_FEN,AnalysisProfile().generator)
            self.assertTrue(repository.put(value));self.assertFalse(repository.put(value))
            changes=db.total_changes
            db.execute("PRAGMA query_only=ON")
            report=diagnostics.inspect(validate_payloads=True)
            self.assertEqual(report.row_count,1)
            self.assertGreater(report.payload_bytes,0)
            self.assertEqual(report.health,"checks_passed")
            self.assertEqual(report.duplicate_keys,0)
            self.assertEqual(report.impossible_rows,0)
            self.assertEqual(report.identities[0].engine_identity,value.engine_identity)
            self.assertEqual(report.oldest_timestamp,report.newest_timestamp)
            self.assertEqual(db.total_changes,changes)

    def test_invalid_json_envelope_and_incomplete_rows_are_visible(self):
        with closing(sqlite3.connect(":memory:")) as db:
            migrate(db)
            repository=CandidateLineRepository(db)
            value=pv_set(chess.STARTING_FEN,AnalysisProfile().generator)
            repository.put(value)
            db.execute("UPDATE engine_candidate_line_cache SET payload_json='not json'")
            report=CandidateLineDiagnosticsService(db).inspect()
            self.assertEqual(report.impossible_rows,1)
            self.assertEqual(report.health,"issues_found")
            self.assertIn("invalid_payload",dict(report.issues))
            data=to_data(value);data["fen"]="different";data["generation_metadata"]["complete"]=False
            db.execute("UPDATE engine_candidate_line_cache SET payload_json=?",(json.dumps(data),))
            report=CandidateLineDiagnosticsService(db).inspect()
            self.assertIn("persisted_incomplete_evidence",dict(report.issues))
            self.assertIn("envelope_identity_mismatch",dict(report.issues))

    def test_duplicate_keys_in_an_incompatible_table_are_reported(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE engine_candidate_line_cache(line_set_id INTEGER PRIMARY KEY,fen TEXT,engine_identity TEXT,schema_version INTEGER,payload_json TEXT,created_at TEXT)")
            value=pv_set(chess.STARTING_FEN,AnalysisProfile().generator)
            for _ in range(2):
                db.execute("INSERT INTO engine_candidate_line_cache(fen,engine_identity,schema_version,payload_json,created_at) VALUES(?,?,?,?,?)",
                    (value.fen,value.engine_identity,1,json.dumps(to_data(value)),"2026-01-01"))
            report=CandidateLineDiagnosticsService(db).inspect()
            self.assertEqual(report.duplicate_keys,1)
            self.assertIn("incompatible_schema",dict(report.issues))
            self.assertEqual(report.health,"issues_found")

    def test_no_desktop_or_hidden_engine_boundary(self):
        root=Path(__file__).resolve().parents[1]
        for name in ("analysis_backbone","analysis_states","settlement_evidence","candidate_line_diagnostics"):
            tree=ast.parse((root/(name+".py")).read_text())
            imports=[n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(value.startswith(("tkinter","merlin_ui","subprocess")) for value in imports))
            if name!="candidate_line_diagnostics": self.assertNotIn("sqlite3",imports)


if __name__=="__main__": unittest.main()
