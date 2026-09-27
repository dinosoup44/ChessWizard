"""Proof provenance is metadata; it must not change chess evidence or analyzer decisions."""
from copy import deepcopy
from dataclasses import asdict, replace
import ast
from pathlib import Path
import unittest
import chess
from analysis_results import HeavyResult
from analysis_settings import load_profile
from candidate_line_request import request_identity
from discovery_evidence import attach_settlements, compact
from settlement_cache import settlement_settings
from settlement_provenance import normalized_settlement_summaries
from tactical_proof import play_proof_move, BoundedProof, ProofWindow


def fixture(stage='selective_settlement_extension', window=12, *, enabled=True):
    p=load_profile('normal_escalation')
    p=replace(p,escalation=replace(p.escalation,settlement_extension=replace(p.escalation.settlement_extension,enabled=enabled)))
    board=chess.Board();board.push_uci('e2e4');steps=[]
    for i,uci in enumerate(('e7e5','g1f3')):
        step,_=play_proof_move(board,board.parse_uci(uci),chess.WHITE,p.scale.material.piece_values(),ply=i,user_moves=0,payoff_plies=9)
        steps.append(step)
    branch=dict(proof_steps=[asdict(s) for s in steps],proof_line='e4 e5 Nf3',proof_state='stable',
        final_fen=board.fen(),final_player_cp=0,state='analyzed_no_hit',classification='rejected')
    details=dict(classification='rejected',reason='fixture',branches=[branch])
    if stage!='breadth':
        proof=BoundedProof('stable',tuple(steps),board.fen(),dict(score_type='cp',score_pov='white',score_cp=0),
            ProofWindow(version='approved_pv_endpoint_v1',settlement_plies=window))
        generator=settlement_settings(p.escalation.verification,window) if enabled else p.escalation.verification
        branch['evidence_stage']=stage
        details['escalation_attempts']=[dict(branch_index=0,status='complete',evidence_stage=stage,proof=asdict(proof),
            request_identities=[(board.fen(),request_identity(generator))])]
    return p,HeavyResult('analyzed_no_hit',details=details)


class SettlementProvenanceTests(unittest.TestCase):
    def test_selective_extension_retains_verification_profile(self):
        profile,result=fixture();attach_settlements(result,'white',profile)
        summary=result.details['branches'][0]['settlement_evidence']
        expected=request_identity(settlement_settings(profile.escalation.verification,12))
        self.assertEqual(summary['proof_profile_identity'],expected)
        self.assertNotEqual(summary['proof_profile_identity'],request_identity(profile.generator))
        provenance=summary['provenance']
        self.assertEqual(provenance['generator']['engine']['depth'],18)
        self.assertEqual(provenance['proof_window']['settlement_plies'],12)
        self.assertEqual(provenance['proof_window']['user_moves'],4)
        self.assertEqual(provenance['proof_window']['version'],'approved_pv_endpoint_v1')
        self.assertEqual(provenance['evidence_stage'],'selective_settlement_extension')
        self.assertEqual(summary['evidence_requests'],[list(result.details['escalation_attempts'][0]['request_identities'][0])])

    def test_normal_verification_uses_actual_eight_ply_source(self):
        for enabled in (False,True):
            profile,result=fixture('verification',8,enabled=enabled);attach_settlements(result,'white',profile)
            summary=result.details['branches'][0]['settlement_evidence'];meta=summary['provenance']
            generator=settlement_settings(profile.escalation.verification,8) if enabled else profile.escalation.verification
            self.assertEqual(summary['proof_profile_identity'],request_identity(generator))
            self.assertEqual(meta['proof_window']['settlement_plies'],8)
            self.assertEqual(meta['generator']['engine']['depth'],18)

    def test_breadth_remains_separate(self):
        profile,result=fixture('breadth',4);attach_settlements(result,'white',profile)
        summary=result.details['branches'][0]['settlement_evidence'];meta=summary['provenance']
        self.assertEqual(summary['proof_profile_identity'],request_identity(profile.generator))
        self.assertEqual(meta['proof_window']['settlement_plies'],4)
        self.assertEqual(meta['generator']['engine']['depth'],12)

    def test_legacy_normalization_is_metadata_only_and_nonmutating(self):
        profile,result=fixture();attach_settlements(result,'white',profile)
        correct=deepcopy(result.details);legacy=compact(correct)
        old=legacy['branches'][0]['settlement_evidence']
        old['proof_profile_identity']=request_identity(profile.generator);old['branch_identity']='legacy';old['evidence_requests']=[];old.pop('provenance')
        before=deepcopy(legacy);normalized=normalized_settlement_summaries(legacy,'white',profile)
        self.assertEqual(legacy,before)
        self.assertEqual(normalized['branches'][0]['settlement_evidence'],correct['branches'][0]['settlement_evidence'])
        self.assertEqual(normalized['classification'],legacy['classification'])
        for key in ('moves_uci','moves_san','captures','observed_material_change_cp','final_evaluation','final_fen','state'):
            self.assertEqual(normalized['branches'][0]['settlement_evidence'][key],old[key])

    def test_summary_does_not_change_verdict_proof_or_scores(self):
        profile,result=fixture();before=deepcopy(result.details);attach_settlements(result,'white',profile)
        actual=deepcopy(result.details);actual['branches'][0].pop('settlement_evidence')
        self.assertEqual(actual,before)
        self.assertEqual(result.state,'analyzed_no_hit')

    def test_unused_recheck_does_not_replace_breadth_provenance(self):
        profile,result=fixture('breadth',4)
        _,deeper=fixture('verification',8)
        attempt=deeper.details['escalation_attempts'][0]
        attempt['proof']['state']='unsettled';result.details['escalation_attempts']=[attempt]
        attach_settlements(result,'white',profile)
        self.assertEqual(result.details['branches'][0]['settlement_evidence']['provenance']['evidence_stage'],'breadth')

    def test_unlabelled_retained_extension_recovers_explicit_stage(self):
        profile,result=fixture();result.details['branches'][0].pop('evidence_stage')
        attach_settlements(result,'white',profile)
        provenance=result.details['branches'][0]['settlement_evidence']['provenance']
        self.assertEqual(provenance['evidence_stage'],'selective_settlement_extension')
        self.assertEqual(provenance['proof_window']['settlement_plies'],12)
        self.assertEqual(provenance['generator']['engine']['depth'],18)

    def test_missing_verification_proof_is_not_guessed(self):
        profile,result=fixture();result.details['escalation_attempts']=[]
        with self.assertRaises(ValueError):attach_settlements(result,'white',profile)

    def test_stale_settlement_facts_are_not_silently_relabelled(self):
        profile,result=fixture();attach_settlements(result,'white',profile)
        result.details['branches'][0]['settlement_evidence']['moves_uci']=['d7d5']
        with self.assertRaises(ValueError):attach_settlements(result,'white',profile)

    def test_provenance_module_has_no_ui_or_persistence_imports(self):
        tree=ast.parse(Path('settlement_provenance.py').read_text(encoding='utf-8-sig'))
        modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        modules += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(m.startswith(('tkinter','sqlite3','subprocess')) for m in modules))


if __name__=='__main__':unittest.main()
