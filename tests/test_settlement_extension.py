"""Selective policy contracts and portable real-evidence regressions; no engine or live DB."""
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
import ast, gzip, json, unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import chess
from analysis_settings import load_profile, SettlementExtensionPolicy
from analyze_forks_v31 import analyze_position
from candidate_line_service import CandidateLineService
from candidate_line_repository import _decode
from candidate_line_request import request_identity
from settlement_cache import SettlementCacheAdapter, settlement_settings
from settlement_extension import SettlementExtensionContext, settlement_extension_eligibility
from tactical_proof import BoundedProof, ProofStep, ProofWindow
from proof_escalation import ProofEscalationService
from test_proof_escalation import pv_set, PVService, request
from analyze_forks_v3 import PIECE_VALUES

ROOT=Path(__file__).resolve().parents[1]


class NoEngine:
    def generate(self,*args,**kwargs):raise AssertionError('Engine search forbidden in cache-only regression')


class RecordedStore:
    def __init__(self,payloads):
        self.payloads={}
        self.decoded={}
        for payload in payloads:
            raw=json.loads(payload)
            self.payloads[(raw['fen'],raw['engine_identity'])]=payload
    def get(self,fen,key):
        pair=(fen,key)
        if pair not in self.payloads:return None
        if pair not in self.decoded:self.decoded[pair]=_decode(self.payloads[pair])
        return self.decoded[pair]


class SettlementCacheTests(unittest.TestCase):
    def setUp(self):
        self.profile=load_profile('normal_escalation');self.base=self.profile.escalation.verification
        self.fen=request().after_tactic_fen
        self.eight=settlement_settings(self.base,8);self.twelve=settlement_settings(self.base,12)

    def service(self,values):
        store=Mock();store.get.side_effect=lambda fen,key:values.get((fen,key))
        return CandidateLineService(NoEngine(),read_stores=(store,))

    def test_exact_twelve_cache_row_reused_without_writes_or_searches(self):
        cached=pv_set(self.fen,self.twelve)
        service=self.service({(self.fen,cached.engine_identity):cached})
        adapter=SettlementCacheAdapter(service,self.base,(8,12))
        self.assertEqual(adapter.candidate_lines(self.fen,self.twelve),cached)
        self.assertEqual(adapter.candidate_lines(self.fen,self.twelve),cached)
        self.assertEqual(adapter.stats['exact_hits'],2)
        self.assertEqual(service.stats['engine_searches'],0)
        self.assertNotEqual(request_identity(self.eight),request_identity(self.twelve))
        with self.assertRaises(AssertionError):adapter.candidate_lines(self.fen,self.eight)

    def test_legacy_compatibility_is_explicit_and_preserves_origin(self):
        legacy=pv_set(self.fen,self.base)
        service=self.service({(self.fen,legacy.engine_identity):legacy})
        adapter=SettlementCacheAdapter(service,self.base,(8,12))
        result=adapter.candidate_lines(self.fen,self.twelve)
        self.assertEqual(result.engine_identity,request_identity(self.twelve))
        self.assertEqual(result.generation_metadata['settlement_cache_compatibility']['source_engine_identity'],legacy.engine_identity)
        self.assertEqual(result.lines[0].pv_uci,legacy.lines[0].pv_uci)
        self.assertNotIn('settlement_cache_compatibility',legacy.generation_metadata)
        self.assertEqual(adapter.stats['compatible_legacy_hits'],1)
        self.assertEqual(service.stats['cache_inserts'],0)
        restricted=('e7e5',)
        with self.assertRaises(AssertionError):adapter.candidate_lines(self.fen,self.twelve,root_moves=restricted)
        deeper=replace(self.twelve,engine=replace(self.twelve.engine,depth=22))
        with self.assertRaises(AssertionError):adapter.candidate_lines(self.fen,deeper)

    def test_disabled_default_and_currentness_do_not_invalidate_breadth(self):
        enabled=replace(self.profile,escalation=replace(self.profile.escalation,
            settlement_extension=SettlementExtensionPolicy(enabled=True)))
        self.assertFalse(self.profile.escalation.settlement_extension.enabled)
        self.assertNotEqual(enabled.currentness_identity,self.profile.currentness_identity)
        self.assertEqual(enabled.engine_identity,self.profile.engine_identity)
        self.assertEqual(enabled.escalation.verification,self.profile.escalation.verification)
        self.assertEqual((enabled.generator.candidate_line_count,enabled.generator.engine.depth,
            enabled.escalation.verification.engine.depth,enabled.escalation.proof.user_moves,
            enabled.escalation.proof.settlement_plies,enabled.escalation.max_escalated_branches_per_candidate,
            enabled.escalation.max_requests_per_candidate),(3,12,18,4,8,3,24))
        definition=next(s for s in enabled.schema() if s.setting_id=='escalation.settlement_extension.enabled')
        self.assertTrue(definition.affects_result_currentness)
        self.assertFalse(definition.affects_raw_cache_identity)

    def test_stable_proof_cannot_be_extended_by_a_forged_eligibility_flag(self):
        p=replace(self.profile,escalation=replace(self.profile.escalation,settlement_extension=SettlementExtensionPolicy(enabled=True)))
        service=ProofEscalationService(PVService(),p);req=request()
        normal=service.escalate(req,PIECE_VALUES)
        self.assertEqual(normal.proof.state,'stable')
        before=service.branches_escalated,len(service.requests.attempted)
        self.assertIs(service.extend_settlement(req,normal,Mock(eligible=True),PIECE_VALUES),normal)
        self.assertEqual(before,(service.branches_escalated,len(service.requests.attempted)))

    def test_specialist_translates_primary_blockers_into_shared_contract(self):
        from analyze_forks_v31 import _extension_context
        from test_fork_multiline import branch_fixture
        context=SimpleNamespace(details={'root_move_passes_gate':True},profile=self.profile)
        mixed=[branch_fixture(),branch_fixture(state='analyzed_no_hit')]
        self.assertIn('genuine_settled_disagreement',_extension_context(context,mixed).blocker_states)
        unsettled=[dict(branch_fixture(),proof_state='unsettled')]
        context.details['escalation_attempts']=[{'branch_index':0,'status':'budget_exhausted','reason':'branch_limit'}]
        self.assertIn('budget_denial_primary_blocker',_extension_context(context,unsettled).blocker_states)
        context.details['escalation_attempts']=[]
        for state,blocker in [('mate','terminal_or_deferred_ownership'),('draw','terminal_or_deferred_ownership'),
                ('missing_continuation','incomplete_evidence')]:
            branches=[dict(branch_fixture(),proof_state=state)]
            self.assertIn(blocker,_extension_context(context,branches).blocker_states)
        self.assertIn('explicit_causality_uncertainty',_extension_context(context,[branch_fixture(critical=True)]).blocker_states)

    def test_terminal_ownership_never_enters_enabled_extension(self):
        board=chess.Board()
        for san in ('f3','e5','g4'):board.push_san(san)
        profile=replace(self.profile,escalation=replace(self.profile.escalation,settlement_extension=SettlementExtensionPolicy(enabled=True)))
        for played,proposed,owner in [('d8h4','b8c6','played_move_terminal'),('b8c6','d8h4','mate')]:
            after=board.copy();move=after.parse_uci(played);san=after.san(move);after.push(move)
            row={'fen_before':board.fen(),'fen_after':after.fen(),'uci_played':played,'san_played':san,'color':'black',
                'move_number':2,'game_id':1,'move_id':1}
            service=CandidateLineService(NoEngine())
            result=analyze_position(row,proposed,service,profile=profile)
            self.assertEqual(result.details['ownership'],owner)
            self.assertEqual(result.details['escalation']['settlement_extensions'],[])
            self.assertEqual(service.stats,Counter())

    def test_core_modules_have_no_desktop_or_database_dependencies(self):
        for name in ('settlement_extension.py','settlement_cache.py','candidate_line_settlement.py'):
            tree=ast.parse((ROOT/name).read_text())
            imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
            self.assertFalse(any(n.startswith(('tkinter','sqlite3','subprocess','merlin_ui')) for n in imports))
