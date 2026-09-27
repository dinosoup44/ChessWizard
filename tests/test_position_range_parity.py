from dataclasses import replace
from copy import deepcopy
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
import chess
from position_range_evidence import analyze_range
from proof_endpoint_facts import collect_endpoint_facts
from tests.support.position_range_parity_audit import compare_range
from tests.support.position_range_parity_reference import replay_reference

VALUES={1:100,2:300,3:300,4:500,5:900,6:0}


def inputs(fen=chess.STARTING_FEN,moves=None,targets=None):
    moves=moves or ['e2e4','d7d5','e4d5'];targets=targets if targets is not None else ['d7']
    p=dict(key='test',fen_before=fen,targets=targets,classification_metadata='verified',
           material_values={chess.piece_name(t):v for t,v in VALUES.items() if t!=chess.KING})
    old=collect_endpoint_facts(fen,moves[0],moves[1:],targets,VALUES)
    r=dict(range_id='test:0',moves_uci=moves,existing_facts=old,proof_steps=[])
    return p,r


class PositionRangeParityTests(unittest.TestCase):
    def test_material_identity_and_attacker_match_independent_replay(self):
        p,r=inputs();result=compare_range(p,r)
        self.assertFalse(result['serious'])
        by={x['field']:x for x in result['comparisons']}
        self.assertEqual(by['material.capture_order_type_color_square_value']['category'],'A')
        self.assertEqual(by['target.d7.square']['category'],'A')
        self.assertEqual(by['attacker.square']['category'],'A')
        self.assertEqual(by['capture.ply_origin']['category'],'B')

    def test_recapture_scope_is_not_engine_best_play(self):
        p,r=inputs('7k/8/8/8/3rb3/8/3R4/K7 w - - 0 1',['d2d4','h8h7'],['d4'])
        result=compare_range(p,r)
        self.assertFalse(result['serious'])
        extra=next(x for x in result['comparisons'] if x['field']=='recapture.additional_participant_captures')
        self.assertEqual(extra['category'],'C')
        self.assertIn('Rxe4',extra['toolkit'])

    def test_attack_and_terminal_semantics(self):
        p,r=inputs('7k/5K2/6Q1/8/8/8/8/8 w - - 0 1',['g6g7'],['h8'])
        result=compare_range(p,r)
        self.assertFalse(result['serious'])
        terminal=next(x for x in result['comparisons'] if x['field']=='terminal.label_normalization')
        self.assertEqual(terminal['category'],'B')
        self.assertEqual(terminal['toolkit'],'checkmate')

    def test_tie_break_identifies_poisoned_old_fact(self):
        p,r=inputs();r['existing_facts']['material_delta_cp']+=100
        result=compare_range(p,r)
        mismatch=next(x for x in result['comparisons'] if x['field']=='material.delta_player')
        self.assertEqual(mismatch['category'],'G')
        self.assertEqual(mismatch['toolkit'],mismatch['independent'])

    def test_tie_break_identifies_poisoned_toolkit_fact(self):
        p,r=inputs();real=analyze_range(p['fen_before'],r['moves_uci'],track_squares=p['targets'],material_snapshots=True)
        with patch('tests.support.position_range_parity_audit.analyze_range',return_value=replace(real,end_fen='bad')):
            result=compare_range(p,r)
        self.assertEqual(next(x for x in result['comparisons'] if x['field']=='endpoint_fen')['category'],'F')

    def test_classification_metadata_cannot_influence_comparison(self):
        p,r=inputs();original=compare_range(p,r)['comparisons']
        for classification in ('rejected','ambiguous','verified_payoff_changed','anything'):
            p['classification_metadata']=classification
            self.assertEqual(compare_range(p,r)['comparisons'],original)

    def test_independent_ep_and_promotion_reference(self):
        ref=replay_reference('7k/8/8/3pP3/8/8/8/7K w - d6 0 2',['e5d6'],VALUES)
        self.assertEqual(ref['captures'][0]['square'],chess.D5)
        self.assertEqual(ref['captures'][0]['victim'],chess.D5)
        ref=replay_reference('1r5k/P7/8/8/8/8/8/7K w - - 0 1',['a7a8q','b8a8'],VALUES)
        self.assertTrue(ref['fates'][chess.A7]['promoted'])
        self.assertEqual(ref['fates'][chess.A7]['capture_ply'],2)

    def test_ep_promotion_and_returned_target_scope(self):
        cases=[('7k/8/8/3pP3/8/8/8/7K w - d6 0 2',['e5d6'],['d5']),
               ('1r5k/P7/8/8/8/8/8/7K w - - 0 1',['a7b8q'],['b8']),
               ('7k/8/8/8/8/8/8/R6K w - - 0 1',['a1a2','h8g8','a2a1','g8h8'],['h8'])]
        for fen,moves,targets in cases:
            with self.subTest(moves=moves):
                p,r=inputs(fen,moves,targets)
                self.assertFalse(compare_range(p,r)['serious'])

    def test_no_engine_ui_database_or_analyzer_verdict_dependency(self):
        p,r=inputs()
        with patch('sqlite3.connect',side_effect=AssertionError('DB')), patch('subprocess.Popen',side_effect=AssertionError('engine')):
            self.assertFalse(compare_range(p,r)['serious'])
        root=Path(__file__).resolve().parents[1]
        for name in ('position_range_parity_audit.py','position_range_parity_reference.py'):
            tree=ast.parse((root/'tests/support'/name).read_text())
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(n.startswith(('tkinter','sqlite3','chess.engine','analyze_forks','analysis_crawler','quality_gate','the_scale')) for n in imports))
