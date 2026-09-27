"""Narrow Fork truth and optional presentation contracts, using portable recorded evidence."""
from dataclasses import replace
from pathlib import Path
import ast,json,sqlite3,unittest
from unittest.mock import patch
import chess
from fork_threats import functional_fork_threats, retain_functional_forks
from exchange_presentation import (build_exchange_presentation, exchange_presentation_from_dict,
    ExchangePresentationSettings, matching_tactical_continuation)
from feedback import FeedbackContextBuilder, FeedbackGenerator
import analyze_forks_v2 as fork
from heavy_adapters import FORK_ROW_FIELDS
from exchange_presentation_repository import StoredExchangeReader

def fail(*args,**kwargs):raise AssertionError('Unexpected engine request')

class FunctionalThreatTests(unittest.TestCase):
    def test_synthetic_pinned_rook_keeps_legal_target(self):
        b=chess.Board('4k3/3N4/4r3/8/8/8/4R3/6K1 b - - 0 1')
        f=functional_fork_threats(b,b.parse_san('Re7'))
        self.assertTrue(f.attacker_pinned);self.assertIn(chess.E2,f.legal_targets)
        self.assertNotIn(chess.D7,f.legal_targets)
    def test_king_safety_filters_defended_capture(self):
        b=chess.Board('5rk1/8/8/8/8/3nPr2/8/4K3 w - - 0 1')
        f=functional_fork_threats(b,b.parse_san('Ke2'))
        self.assertIn(chess.D3,f.legal_targets);self.assertNotIn(chess.F3,f.legal_targets)
        self.assertFalse(f.valid)
    def test_optional_detail_preserves_game_source_and_short_answer(self):
        from test_heavy_services import move_row
        row=move_row('r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1','e1f1')
        def position(fen,profile):
            b=chess.Board(fen)
            pv='Kf7 Nxa8' if b.piece_at(chess.C7)==chess.Piece(chess.KNIGHT,chess.WHITE) else ''
            return {'score_type':'cp','score_cp':-200 if fen==row['fen_after'] else 300,
                    'mate':None,'principal_variation':pv}
        result=fork.analyze_single_move(tuple(row[k] for k in FORK_ROW_FIELDS),position)
        self.assertEqual(result['source'],row['source'])
        self.assertEqual(result['source_game_id'],row['source_game_id'])
        self.assertEqual(result['candidate']['solution_line'],'Nc7+ Kf7 Nxa8')
        self.assertEqual(json.loads(result['candidate']['metadata_json'])['exchange_presentation']['state'],'terminal')

class ExchangePresentationTests(unittest.TestCase):
    def test_terminal_and_invalid_evidence(self):
        d=build_exchange_presentation('7k/5K2/6Q1/8/8/8/8/8 w - - 0 1','Qg7#','')
        self.assertEqual(d.state,'terminal')
        with self.assertRaises(ValueError):build_exchange_presentation(chess.STARTING_FEN,'e4','e5 Qh9')
    def test_settings_typed_range_and_no_proof_currentness(self):
        self.assertEqual(ExchangePresentationSettings().schema('presentation.exchange.')[0].setting_id,'presentation.exchange.max_plies')
        self.assertFalse(ExchangePresentationSettings().schema()[0].affects_result_currentness)
        with self.assertRaises(ValueError):ExchangePresentationSettings(max_plies=0)
    def test_core_has_no_ui_engine_or_persistence_imports(self):
        for name in ('fork_threats.py','exchange_presentation.py'):
            tree=ast.parse((Path(__file__).parents[1]/name).read_text(encoding='utf-8-sig'))
            imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any(m and ('tkinter' in m or 'sqlite' in m or m=='chess.engine') for m in imports))

if __name__=='__main__':unittest.main()
