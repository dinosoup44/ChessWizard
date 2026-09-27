"""Contract tests use legal supplied lines, never an engine or live database."""
from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import chess
from analysis_settings import MaterialValues
from critical_moment_context import EvaluationEvidence
from major_material_blunder_models import MaterialBlunderPolicy
from major_material_blunders import check_major_material_blunder
from position_range_evidence import LegalReplay


def check(fen, sans, **kwargs):
    board = chess.Board(fen)
    ucis = []
    for san in sans:
        move = board.parse_san(san)
        ucis.append(move.uci())
        board.push(move)
        if len(ucis) == 1:
            after = board.fen()
    return check_major_material_blunder(chess.Board(fen), ucis[0], after, ucis[1:], **kwargs)


def quiet_loss(piece="Q", defender="", enemy="r"):
    return f"3{enemy}3k/8/8/8/8/8/1P1{piece}4/K{defender}6 w - - 0 1" if defender else f"3{enemy}3k/8/8/8/8/8/1P1{piece}4/K7 w - - 0 1"


class MaterialBlunderTests(unittest.TestCase):
    def test_confirmed_queen_rook_and_minors(self):
        for symbol, kind, value in (("Q","hung_queen",900),("R","hung_rook",500),
                                    ("B","hung_minor_piece",300),("N","hung_minor_piece",300)):
            with self.subTest(symbol=symbol):
                r = check(quiet_loss(symbol), ("b3","Rxd2","Kb1","Kg8","Ka1"))
                self.assertEqual((r.classification,r.blunder_type,r.net_loss_cp),("confirmed",kind,value),r)
                self.assertTrue(r.attack_after.legal_capture_available)
                self.assertIsNone(r.attack_before.legal_capture_available)
                self.assertEqual(r.exposure_cause,"ignored_existing_direct_threat")
                self.assertIsNotNone(r.avoidance_witness)
                self.assertEqual(r.target_fate.capture_ply,2)

    def test_new_exposure(self):
        r=check("3r3k/8/8/8/8/8/1P6/K1Q5 w - - 0 1",("Qd2","Rxd2","Kb1","Kg8"))
        self.assertEqual(r.classification,"confirmed",r)
        self.assertEqual(r.exposure_cause,"moved_target_into_capture")

    def test_abandoned_defender(self):
        r=check("3r3k/8/8/8/8/1P6/3Q4/K1B5 w - - 0 1",("Ba3","Rxd2","Kb1","Kg8"))
        self.assertNotEqual(r.classification,"confirmed")  # The bishop has forcing checks.
        self.assertEqual(r.exposure_cause,"abandoned_defender")

    def test_equal_queen_and_rook_trade(self):
        for piece,enemy in (("Q","q"),("R","r")):
            r=check(f"3{enemy}3k/8/8/8/8/8/1P1{piece}4/K1B5 w - - 0 1",
                ("b3",f"{enemy.upper()}xd2","Bxd2","Kg8"))
            self.assertEqual(r.classification,"not_blunder",r)
            self.assertEqual(r.net_loss_cp,0)
            self.assertTrue(r.immediate_recapture_available)

    def test_unplayed_equal_recovery_is_not_ignored(self):
        r=check("3r3k/8/8/8/8/8/1P1R4/K1B5 w - - 0 1",("b3","Rxd2","Kb1","Kg8"))
        self.assertEqual(r.classification,"unresolved",r)
        self.assertEqual(r.reason,"alternative_material_recovery")

    def test_pinned_geometric_capturer(self):
        r=check("4k3/4b3/3Q4/8/8/8/8/K3R3 w - - 0 1",("Kb1","Kf8","Qb4"),target_square="d6")
        self.assertEqual(r.classification,"not_blunder",r)
        self.assertIn(chess.E7,r.attack_after.geometric_attackers)
        self.assertFalse(r.attack_after.legal_capture_available)

    def test_forced_mate_compensates_sacrifice(self):
        r=check("6rk/5Q1p/5R2/8/8/8/1B6/K7 w - - 0 1",("Qg7+","Rxg7","Rf8#"))
        self.assertEqual((r.classification,r.reason),("not_blunder","terminal_compensation"))
        self.assertEqual(r.terminal_state.winner,chess.WHITE)

    def test_already_doomed_has_no_new_blunder_claim(self):
        r=check("3kr3/8/8/1b6/8/8/P3Q3/4K3 w - - 0 1",("a3","Rxe2+","Kd1","Re3","Kc1"))
        self.assertEqual((r.classification,r.reason),("unresolved","prior_loss_not_excluded"),r)
        self.assertIsNone(r.avoidance_witness)

    def test_attack_without_loss_and_safe_move(self):
        r=check(quiet_loss(),("b3","Kg8","Qc2"),target_square="d2")
        self.assertEqual(r.reason,"target_survived")
        self.assertTrue(r.attack_after.legal_capture_available)
        self.assertTrue(r.target_fate.alive)

    def test_promotion_credit_and_identity(self):
        r=check("7r/6Pk/8/8/8/8/8/K7 w - - 0 1",("g8=Q+","Rxg8","Kb1","Kh6"))
        self.assertNotEqual(r.classification,"confirmed",r)
        self.assertEqual(r.target_piece_id.initial_piece_type,chess.PAWN)
        self.assertEqual(r.target_piece_type,chess.QUEEN)
        self.assertEqual(r.net_loss_cp,100)
        self.assertEqual(r.material_transition.promotion_delta.white,800)

    def test_en_passant_credit(self):
        r=check("3r3k/8/8/4Pp2/8/8/3Q4/K7 w - f6 0 1",("exf6","Rxd2","Kb1","Kg8"))
        self.assertEqual(r.material_recovered_cp,100)
        self.assertEqual(r.net_loss_cp,800)
        self.assertTrue(r.range_evidence.moves[0].capture.en_passant)

    def test_castling_preserves_rook_identity(self):
        r=check("k2r4/8/8/8/8/8/8/4K2R w K - 0 1",("O-O","Rd2","Rf2","Rxf2","Kxf2"),target_square="h1")
        self.assertEqual((r.classification,r.reason),("unresolved","loss_not_immediate"))
        self.assertEqual(r.target_piece_id.initial_square,chess.H1)
        self.assertEqual(r.target_fate.capture_ply,4)
        self.assertTrue(r.range_evidence.moves[0].castling)

    def test_terminal_source(self):
        fen="7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
        r=check_major_material_blunder(fen,"h8g8",fen)
        self.assertEqual((r.classification,r.reason),("not_blunder","terminal_source"))

    def test_multiple_attackers(self):
        r=check("3r3k/8/8/8/8/4b3/1P1Q4/K7 w - - 0 1",("b3","Rxd2","Kb1","Kg8"))
        self.assertEqual(r.classification,"confirmed",r)
        self.assertEqual(set(r.attack_after.legal_attackers),{chess.D8,chess.E3})

    def test_recovery_elsewhere_not_just_recapture(self):
        r=check("3r3k/8/8/8/8/7q/1P1Q4/K5R1 w - - 0 1",("b3","Rxd2","Kb1","Kh7"))
        self.assertNotEqual(r.classification,"confirmed",r)
        # A second example supplies the actual equal capture rather than assuming it.
        r=check("3r3k/8/8/8/8/6q1/1P1Q4/K5R1 w - - 0 1",("b3","Rxd2","Rxg3","Kh7"))
        self.assertEqual(r.net_loss_cp,0)
        self.assertEqual(r.classification,"not_blunder",r)

    def test_source_immutable_and_ledger_reconciles(self):
        board=chess.Board(quiet_loss()); snapshot=(board.fen(),tuple(board.move_stack))
        after=board.copy();after.push_uci("b2b3")
        r=check_major_material_blunder(board,"b2b3",after,("d8d2","a1b1","h8g8"))
        self.assertEqual(snapshot,(board.fen(),tuple(board.move_stack)))
        e=LegalReplay(board,("b2b3","d8d2","a1b1","h8g8")).evidence(track_squares=("d2",),material_snapshots=True)
        self.assertEqual(r.range_evidence,e)
        self.assertEqual(r.net_loss_cp,e.material_transition.delta.black-e.material_transition.delta.white)
        with self.assertRaises(FrozenInstanceError):r.net_loss_cp=0
        json.dumps(asdict(r))

    def test_illegal_mismatched_and_missing_evidence(self):
        fen=quiet_loss();after=chess.Board(fen);after.push_uci("b2b3")
        self.assertEqual(check_major_material_blunder(fen,"b2b3",after).classification,"unresolved")
        self.assertEqual(check_major_material_blunder(fen,"b2b3",fen,("d8d2",)).classification,"error")
        self.assertEqual(check_major_material_blunder(fen,"b2b3",after,("h8a1",)).classification,"error")
        self.assertEqual(check_major_material_blunder(fen,"0000",fen).classification,"error")
        r=check_major_material_blunder(fen,"b2b3",after,("d8d2","a1b1","h8g8","b1a1","g8h8"))
        self.assertEqual(r.classification,"error")

    def test_policy_and_material_values(self):
        r=check(quiet_loss(),("b3","Rxd2","Kb1","Kg8"),material_values=MaterialValues(queen=1000))
        self.assertEqual(r.net_loss_cp,1000)
        schema=MaterialBlunderPolicy().schema("material_blunder.")
        self.assertTrue(all(x.affects_result_currentness and not x.affects_raw_cache_identity for x in schema))
        with self.assertRaises(ValueError):MaterialBlunderPolicy(continuation_plies=5)

    def test_cached_score_never_admits_or_invents(self):
        fen=quiet_loss();after=chess.Board(fen);after.push_uci("b2b3")
        eb=EvaluationEvidence(fen,"same","fixture",300)
        ea=EvaluationEvidence(after.fen(),"same","fixture",-600)
        r=check(fen,("b3","Rxd2","Kb1","Kg8"),eval_before=eb,eval_after=ea)
        self.assertEqual(r.eval_delta,-900)
        self.assertEqual(r.classification,"confirmed")
        r=check(fen,("b3","Rxd2","Kb1","Kg8"),eval_before=eb,
            eval_after=EvaluationEvidence(after.fen(),"different","fixture",-600))
        self.assertIsNone(r.eval_delta)
        r=check(fen,("b3","Rxd2","Kb1","Kg8"),eval_after=eb)
        self.assertEqual(r.classification,"error")

    def test_opened_line(self):
        r=check("3r3k/8/8/8/8/1P1B4/3Q4/K7 w - - 0 1",("Bc4","Rxd2","Kb1","Kh7"))
        self.assertEqual(r.exposure_cause,"opened_capture_line")
        self.assertFalse(r.attack_before.geometric_attackers)
        self.assertTrue(r.attack_after.legal_capture_available)

    def test_cutoff_recapture_is_unsettled(self):
        r=check("3r3k/8/8/8/1b6/8/1P1R4/K1B5 w - - 0 1",("b3","Rxd2","Bxd2"))
        self.assertEqual((r.classification,r.reason),("unresolved","recovery_unsettled"))
        self.assertEqual(r.net_loss_cp,0)

    def test_rook_for_only_pawn_and_settings_margin(self):
        fen="3r3k/8/8/4Pp2/8/8/3R4/K7 w - f6 0 1"
        line=("exf6","Rxd2","Kb1","Kh7")
        r=check(fen,line)
        self.assertEqual((r.classification,r.net_loss_cp),("confirmed",400))
        strict=check(fen,line,policy=MaterialBlunderPolicy(recovery_pawns=0))
        self.assertEqual(strict.classification,"unresolved")
        self.assertNotEqual(strict.policy_identity,r.policy_identity)

    def test_forcing_compensation_never_assumed_harmless(self):
        fen="3r3k/8/8/8/8/1P6/3Q4/K1B5 w - - 0 1"
        r=check(fen,("Ba3","Rxd2","Kb1","Kg8"))
        self.assertEqual((r.classification,r.reason),("unresolved","forcing_compensation_unproved"))
        self.assertTrue(r.unresolved_forcing_moves)


    def test_portable_import_and_no_effects(self):
        code = """
import builtins
old=builtins.__import__
def guarded(name,*args,**kwargs):
    if name in ('sqlite3','chess.engine','tkinter') or name.startswith(('merlin_ui','analyze_')):
        raise AssertionError(name)
    return old(name,*args,**kwargs)
builtins.__import__=guarded
import major_material_blunders
"""
        subprocess.run([sys.executable,"-B","-c",code],check=True,capture_output=True,text=True)
        with patch('sqlite3.connect',side_effect=AssertionError("database")), patch('subprocess.Popen',side_effect=AssertionError("engine")):
            r=check(quiet_loss(),("b3","Rxd2","Kb1","Kg8"))
        self.assertEqual(r.classification,"confirmed")


if __name__ == "__main__":
    unittest.main()
