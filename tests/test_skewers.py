from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
import chess

from analysis_crawler import ANALYZERS, coverage_decision
from analyze_skewers import analyze_single_move
from board_analysis import direct_slider_lines, ray_contacts, direction
from heavy_adapters import dispatch_heavy
from heavy_repository import save_heavy_result
from analysis_results import HeavyResult
from pin_geometry import pins_from
from skewer_geometry import skewering_moves, skewers_from, skewer_screener
from skewer_scout import scout_skewer, skewer_scout_config
from skewer_adapter import skewer_adapter
from tactical_opportunities import opportunity_to_dict, opportunity_from_dict
from tactical_opportunity_repository import read_candidate_opportunity
from tactical_fixtures import move_context, scripted_evidence
import test_heavy_services as fixtures

GOLD = json.loads((Path(__file__).parent/'fixtures/skewer_v1_gold.json').read_text())


def case_named(name):
    return next(c for c in GOLD['cases'] if c['case_id']==name)


def calculate(name):
    case = case_named(name)
    row = move_context(case['fen'],case['played_uci'])
    evaluate,_ = scripted_evidence(row,case['prefix'])
    return row,analyze_single_move(row,evaluate)


class SkewerTests(unittest.TestCase):
    def test_geometry_enumeration_preserves_board_and_supports_slider_promotions(self):
        board=chess.Board(case_named('king_rook_diagonal')['fen'])
        snapshot=board.fen(),list(board.move_stack)
        self.assertTrue(list(skewering_moves(board)))
        self.assertEqual((board.fen(),board.move_stack),snapshot)
        promotion=chess.Board('8/6P1/4k3/8/2r5/8/8/7K w - - 0 1')
        choices={c.move_uci for c in skewering_moves(promotion)}
        self.assertIn('g7g8b',choices)
        self.assertIn('g7g8q',choices)
        self.assertNotIn('g7g8n',choices)

    def test_king_recapture_charged_without_rewriting_first_front_response(self):
        case=case_named('king_rook_diagonal'); row=move_context(case['fen'],case['played_uci'])
        evaluate,_=scripted_evidence(row,'Bb2+ Ke4 Bxe5 Kxe5')
        result=analyze_single_move(row,evaluate)
        self.assertEqual(result.state,'candidate',result.details)
        self.assertEqual(result.opportunity.metadata['front_resolution'],'moved')
        self.assertTrue(result.opportunity.metadata['attacker_exchanged'])
        self.assertEqual(result.opportunity.proof.retained_material_gain_cp,200)
        self.assertEqual(result.opportunity.primary_outcome.kind,'win_exchange')

    def test_all_curated_contract_cases(self):
        for case in GOLD['cases']:
            with self.subTest(case=case['case_id']):
                board = chess.Board(case['fen'])
                self.assertTrue(board.is_valid())
                snapshot = board.fen(),list(board.move_stack)
                if case.get('geometry_only'):
                    found = any(c.move_uci==case['tactic_uci'] for c in skewering_moves(board))
                    self.assertEqual(found,case['expected_created'])
                else:
                    row = move_context(case['fen'],case['played_uci'])
                    if case.get('mate_score'):
                        evaluate = lambda fen,profile:{'score_type':'mate','score_pov':'white','mate':3}
                    else:
                        evaluate,_ = scripted_evidence(row,case['prefix'])
                    result = analyze_single_move(row,evaluate)
                    self.assertEqual(result.state,case['expected'],result.details)
                    if result.state=='candidate':
                        self.assertTrue(skewer_screener(row))
                        self.assertEqual(result.opportunity.motifs[0].attribution,'supported')
                        self.assertTrue(result.opportunity.proof.settled_position_reached)
                self.assertEqual((board.fen(),board.move_stack),snapshot)

    def test_shared_lines_do_not_skip_blockers_or_apply_tactic_policy(self):
        case = case_named('two_blockers')
        board = chess.Board(case['fen']); board.push_uci('c1b2')
        line = next(l for l in direct_slider_lines(board,chess.B2) if l.step==(1,1))
        self.assertEqual((line.front.square,line.rear.square),(chess.C3,chess.D4))
        self.assertEqual(len(ray_contacts(board,chess.B2,(1,1))),3)
        self.assertFalse(skewers_from(board,chess.B2))
        self.assertEqual(direction(line.attacker.square,line.rear.square),line.step)

    def test_pin_and_skewer_have_opposite_importance_policy(self):
        board = chess.Board(case_named('queen_rook_diagonal')['fen']); board.push_uci('c1b2')
        self.assertTrue(skewers_from(board,chess.B2))
        self.assertFalse(pins_from(board,chess.B2))
        board.set_piece_at(chess.D4,chess.Piece(chess.KNIGHT,chess.BLACK))
        self.assertFalse(skewers_from(board,chess.B2))
        self.assertTrue(pins_from(board,chess.B2))

    def test_played_and_already_existing_relationship_excluded(self):
        case = case_named('king_rook_diagonal')
        board = chess.Board(case['fen'])
        self.assertNotIn('c1b2',{c.move_uci for c in skewering_moves(board,'c1b2')})
        board.push_uci('c1b2'); board.turn=chess.WHITE
        self.assertNotIn('b2a1',{c.move_uci for c in skewering_moves(board)})

    def test_timing_and_meaningful_outcome(self):
        _,immediate = calculate('king_rook_diagonal')
        _,delayed = calculate('delayed_rear')
        self.assertEqual(immediate.opportunity.payoff_timing,'immediate')
        self.assertEqual(delayed.opportunity.payoff_timing,'delayed')
        self.assertEqual(immediate.opportunity.primary_outcome.kind,'win_rook')
        self.assertEqual(immediate.opportunity.presentation.title,'Check and win the rook')
        self.assertEqual(immediate.opportunity.proof.score_pov,'white')

    def test_black_mirror_and_board_context_immutability(self):
        case = case_named('king_rook_diagonal')
        original = chess.Board(case['fen']); mirrored = original.mirror()
        prefix=[]
        for san in case['prefix'].split():
            move=original.parse_san(san)
            mirrored_move=chess.Move(chess.square_mirror(move.from_square),chess.square_mirror(move.to_square),promotion=move.promotion)
            prefix.append(mirrored.san(mirrored_move)); original.push(move); mirrored.push(mirrored_move)
        row=move_context(chess.Board(case['fen']).mirror().fen(),'h8g8'); snapshot=dict(row)
        evaluate,_=scripted_evidence(row,' '.join(prefix))
        result=analyze_single_move(row,evaluate)
        self.assertEqual(result.state,'candidate',result.details)
        self.assertEqual(result.opportunity.proof.score_pov,'black')
        self.assertEqual(row,snapshot)

    def test_front_capture_and_attacker_exchange_are_accounted(self):
        _,captured=calculate('front_captured'); _,exchanged=calculate('attacker_exchange')
        self.assertEqual(captured.opportunity.metadata['front_resolution'],'captured_by_attacker')
        self.assertEqual(captured.opportunity.primary_outcome.kind,'win_queen')
        self.assertTrue(exchanged.opportunity.metadata['attacker_exchanged'])
        self.assertEqual(exchanged.opportunity.metadata['related_retained_material_cp'],900)
        self.assertEqual(exchanged.opportunity.primary_outcome.kind,'force_favorable_exchange')
        self.assertEqual(exchanged.opportunity.primary_outcome.target_piece,'queen')

    def test_unrelated_gain_and_front_only_exchange_are_not_skewers(self):
        for name in ('unrelated_gain','front_takes_attacker'):
            _,result=calculate(name)
            self.assertEqual(result.state,'analyzed_no_hit')
            self.assertIn('rear_payoff_not_proven',{r['reason'] for r in result.details['rejections']})
            self.assertIsNone(result.opportunity)

    def test_uncompelled_front_and_recapture_loss_rejected(self):
        for name,reason in (('front_not_compelled','front_resolution_not_compelling'),('rear_recaptured','material_not_retained')):
            _,result=calculate(name)
            self.assertEqual(result.state,'analyzed_no_hit')
            self.assertIn(reason,{r['reason'] for r in result.details['rejections']})

    def test_mate_ownership_and_failed_final_evaluation(self):
        case=case_named('king_rook_diagonal'); row=move_context(case['fen'],case['played_uci'])
        for mate in (-2,2):
            result=analyze_single_move(row,lambda f,p:{'score_type':'mate','score_pov':'white','mate':mate})
            self.assertEqual(result.state,'analyzed_no_hit')
            self.assertEqual(result.details['reason'],'mate_score_deferred')
            self.assertEqual(result.details['deferred_motifs'][0]['attribution'],'context_only')
        evaluate,fens=scripted_evidence(row,case['prefix'])
        def losing(fen,profile):
            raw=evaluate(fen,profile)
            if fen in fens[5:]: raw['score_cp']=-200
            return raw
        result=analyze_single_move(row,losing)
        self.assertEqual(result.state,'analyzed_no_hit')
        self.assertIn('continuation_not_sustained',{r['reason'] for r in result.details['rejections']})

    def test_scout_threshold_and_mate_recall_are_explicit(self):
        for loss,expected in ((79,False),(80,True)):
            evidence=Mock(); evidence.for_player.side_effect=[{'score_type':'cp','score_cp':100},{'score_type':'cp','score_cp':100-loss}]
            self.assertEqual(scout_skewer({},evidence).send_to_heavy,expected)
        evidence=Mock(); evidence.for_player.side_effect=[{'score_type':'mate','mate':-2},{'score_type':'cp','score_cp':0}]
        self.assertTrue(scout_skewer({},evidence).send_to_heavy)
        config=json.loads(skewer_scout_config())
        self.assertEqual(config['thresholds']['min_loss_cp'],80)
        self.assertEqual(config['profile']['limit_value'],10000)
        definition=ANALYZERS['missed_skewer']
        self.assertEqual((definition.screener_version,definition.scout_version,definition.analyzer_version),('1','1','1'))

    def test_adapter_uses_supplied_position_service_and_invalid_rows_retry(self):
        case=case_named('king_rook_diagonal'); row=move_context(case['fen'],case['played_uci'])
        evaluate,_=scripted_evidence(row,case['prefix'])
        positions=Mock(); positions.position.side_effect=evaluate
        self.assertEqual(skewer_adapter(row,positions).state,'candidate')
        self.assertEqual({call.args[1] for call in positions.position.call_args_list},{'tactic_quick_v1','tactic_verify_v1'})
        bad={**row,'color':'unknown'}
        self.assertTrue(skewer_screener(bad))
        result=dispatch_heavy(ANALYZERS['missed_skewer'],Mock(),Mock(),bad,{},position_service=positions)
        self.assertEqual(result.state,'error')


class SkewerRepositoryTests(unittest.TestCase):
    setUp=fixtures.RepositoryTests.setUp

    def test_opportunity_roundtrip_canonical_columns_and_noop_rerun(self):
        row,result=calculate('king_rook_diagonal'); definition=ANALYZERS['missed_skewer']
        document=opportunity_to_dict(result.opportunity)
        self.assertEqual(opportunity_to_dict(opportunity_from_dict(document)),document)
        saved=save_heavy_result(self.c,definition,row,result,{(1,'missed_skewer')},coverage_decision)
        self.assertEqual(saved['action'],'candidate_created')
        metadata=json.loads(self.c.execute('SELECT metadata_json FROM tactic_candidates').fetchone()[0])
        self.assertNotIn('line_san',metadata['tactical_opportunity']['proof'])
        self.c.execute('ALTER TABLE moves ADD COLUMN uci_played TEXT')
        self.c.execute('UPDATE moves SET uci_played=? WHERE move_id=1',(row['uci_played'],)); self.c.commit()
        self.assertEqual(read_candidate_opportunity(self.c,saved['candidate_id']).opportunity,result.opportunity)
        before=self.c.total_changes
        rerun=save_heavy_result(self.c,definition,row,result,{(1,'missed_skewer')},coverage_decision)
        self.assertEqual(rerun['action'],'unchanged'); self.assertEqual(self.c.total_changes,before)

    def test_candidate_id_training_link_and_rejected_rows_preserved(self):
        row,result=calculate('king_rook_diagonal'); definition=ANALYZERS['missed_skewer']
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,detector_version) VALUES(42,1,'missed_skewer',0)")
        self.c.execute('INSERT INTO training_attempts VALUES(1,42)'); self.c.commit()
        saved=save_heavy_result(self.c,definition,row,result,{(1,'missed_skewer')},coverage_decision)
        self.assertEqual(saved['candidate_id'],42)
        self.assertEqual(self.c.execute('SELECT candidate_id FROM training_attempts').fetchone()[0],42)
        self.c.execute("UPDATE analysis_coverage SET coverage_status='rejected',analyzer_version='0'")
        self.c.execute("UPDATE tactic_candidates SET candidate_status='rejected'"); self.c.commit()
        before=self.c.total_changes
        saved=save_heavy_result(self.c,definition,row,HeavyResult('analyzed_no_hit'),{(1,'missed_skewer')},coverage_decision)
        self.assertEqual(saved['action'],'protected'); self.assertEqual(self.c.total_changes,before)
        self.assertFalse(self.c.execute('PRAGMA foreign_key_check').fetchall())


if __name__=='__main__':
    unittest.main()
