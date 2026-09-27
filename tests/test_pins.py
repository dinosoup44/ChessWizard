from collections import Counter
from dataclasses import replace
from contextlib import closing, redirect_stderr
import io
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

import chess

from analysis_crawler import ANALYZERS, coverage_decision, parse_args
from board_analysis import attackers, legal_mobility, material_balance, piece_safety
from heavy_adapters import dispatch_heavy
from heavy_repository import save_heavy_result
from pin_geometry import pins_from, pinning_moves, pin_screener, PIECE_VALUES
from pin_scout import scout_pin, pin_scout_config
from pin_adapter import pin_adapter
from analyze_pins import analyze_single_move, related_capture
from test_heavy_services import move_row
import test_heavy_services as repository_fixtures


ABSOLUTE_FEN = "8/p7/8/8/3k4/2n5/3P4/2B4K w - - 0 1"
RELATIVE_FEN = "8/p6k/8/8/3q4/2n5/3P4/2B4K w - - 0 1"


def mirror_uci(uci):
    move = chess.Move.from_uci(uci)
    return chess.Move(chess.square_mirror(move.from_square), chess.square_mirror(move.to_square), promotion=move.promotion).uci()


def proof_fixture(relative=False, mirrored=False, exposed=False):
    board = chess.Board(RELATIVE_FEN if relative else ABSOLUTE_FEN)
    moves = ["c1b2", "c3b5" if exposed else "a7a6", "b2d4" if exposed else "b2c3",
             "a7a6" if exposed else "d4d5" if relative else "d4c5"]
    played = "h1h2"
    if mirrored:
        board = board.mirror()
        moves, played = [mirror_uci(m) for m in moves], mirror_uci(played)
    row = move_row(board.fen(), played)
    fens, sans = [board.fen()], []
    for uci in moves:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise AssertionError(f"Invalid fixture move {uci} in {board.fen()}")
        sans.append(board.san(move))
        board.push(move)
        fens.append(board.fen())
    def evaluate(fen, profile):
        cp = 0 if fen == row["fen_after"] else 300 if fen in fens else -500
        pv = " ".join(sans[1:3]) if fen == fens[1] else sans[3] if fen == fens[3] else ""
        return {"score_type":"cp","score_cp":-cp if mirrored else cp,"mate":None,
                "score_pov":"white","principal_variation":pv,"cache_id":42}
    return row, evaluate, fens, sans


class PinGeometryTests(unittest.TestCase):
    def test_bishop_absolute_pin_restricts_legal_moves_but_not_attacks(self):
        board = chess.Board(ABSOLUTE_FEN)
        board.push_uci("c1b2")
        pins = pins_from(board,chess.B2)
        self.assertEqual(len(pins),1)
        self.assertEqual((pins[0].pinned.square,pins[0].behind.square,pins[0].pin_type), (chess.C3,chess.D4,"absolute"))
        self.assertEqual(legal_mobility(board,chess.C3).move_count,0)
        self.assertIn(chess.C3, attackers(board,chess.A4,chess.BLACK))
        self.assertTrue(piece_safety(board,chess.C3).absolutely_pinned)

    def test_relative_pin_to_queen_and_rook_allows_blocker_move(self):
        for target in ("q","r"):
            board = chess.Board(RELATIVE_FEN.replace("3q4",f"3{target}4"))
            board.push_uci("c1b2")
            pin = pins_from(board,chess.B2)[0]
            self.assertEqual(pin.pin_type,"relative")
            self.assertIn("c3b5",legal_mobility(board,chess.C3).moves_uci)
            self.assertFalse(piece_safety(board,chess.C3).absolutely_pinned)

    def test_absolute_pin_can_move_along_line(self):
        board = chess.Board("4k3/4r3/8/8/8/8/8/K3R3 b - - 0 1")
        self.assertEqual(pins_from(board,chess.E1)[0].pin_type,"absolute")
        self.assertIn("e7e6",legal_mobility(board,chess.E7).moves_uci)
        self.assertNotIn("e7d7",legal_mobility(board,chess.E7).moves_uci)

    def test_rook_file_rank_and_queen_geometry_both_colors(self):
        fixtures = [("q6k/8/8/8/8/b7/8/R6K w - - 0 1",chess.A1),
                    ("7k/8/8/8/8/8/8/R1b3qK w - - 0 1",chess.A1),
                    ("7k/8/8/8/3q4/2n5/1Q6/7K w - - 0 1",chess.B2)]
        for fen, square in fixtures:
            board = chess.Board(fen)
            for position, source in ((board,square),(board.mirror(),chess.square_mirror(square))):
                self.assertEqual(pins_from(position,source)[0].pin_type,"relative")

    def test_blocked_ray_and_two_blockers_are_not_direct_pin_to_distant_target(self):
        for fen in ("q6k/8/8/8/8/P7/8/R6K w - - 0 1",
                    "q6k/8/8/8/n7/n7/8/R6K w - - 0 1",
                    "Q6k/8/8/8/8/n7/8/R6K w - - 0 1"):
            self.assertEqual(pins_from(chess.Board(fen),chess.A1),())

    def test_screener_alternatives_existing_pin_and_board_immutability(self):
        row = move_row(ABSOLUTE_FEN,"h1h2")
        self.assertTrue(pin_screener(row))
        board = chess.Board(ABSOLUTE_FEN)
        original = board.fen()
        alternatives = tuple(pinning_moves(board,"c1b2"))
        self.assertNotIn("c1b2",[p.move_uci for p in alternatives])
        self.assertEqual(board.fen(),original)
        board.push_uci("c1b2")
        board.push_uci("a7a6")
        self.assertNotIn("b2a1",[p.move_uci for p in pinning_moves(board)])
        self.assertTrue(pin_screener({**row,"fen_before":"invalid"}))
        self.assertFalse(pin_screener(move_row()))

    def test_promotion_creates_slider_pin_and_castling_is_excluded(self):
        board = chess.Board("8/Pn6/2k5/8/8/8/8/7K w - - 0 1")
        found = {p.move_uci for p in pinning_moves(board)}
        self.assertIn("a7a8b",found)
        self.assertIn("a7a8q",found)
        castling = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertNotIn("e1g1",{p.move_uci for p in pinning_moves(castling)})


class PinScoutTests(unittest.TestCase):
    def test_threshold_mate_retention_and_config_identity(self):
        for loss, expected in ((79,False),(80,True),(120,True)):
            evidence = Mock()
            evidence.for_player.side_effect = [{"score_type":"cp","score_cp":0}, {"score_type":"cp","score_cp":-loss}]
            self.assertEqual(scout_pin({},evidence).send_to_heavy,expected)
            self.assertEqual(evidence.for_player.call_args_list[1].kwargs,{"after":True})
        evidence = Mock()
        evidence.for_player.return_value = {"score_type":"mate","mate":-2}
        self.assertTrue(scout_pin({},evidence).send_to_heavy)
        config = json.loads(pin_scout_config())
        self.assertEqual(config["thresholds"]["min_loss_cp"],80)
        self.assertEqual(config["profile"]["limit_value"],10000)

    def test_only_readonly_preview_allows_analysis_filter_in_saved_scope(self):
        with patch("sys.argv",["crawler","--validation-scope-500","--negative-preview","--analysis","missed_pin"]):
            args = parse_args()
        self.assertEqual(args.analysis,["missed_pin"])
        self.assertFalse(args.write_negatives)
        with patch("sys.argv",["crawler","--validation-scope-500","--write-negatives","--analysis","missed_pin"]), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args()


class PinSpecialistTests(unittest.TestCase):
    def test_absolute_relative_and_both_colors_produce_verified_candidate(self):
        for relative, mirrored in ((False,False),(True,False),(False,True),(True,True)):
            with self.subTest(relative=relative,mirrored=mirrored):
                row, evaluate, fens, sans = proof_fixture(relative,mirrored)
                original = row.copy()
                service = Mock()
                service.position.side_effect = evaluate
                result = pin_adapter(row,service)
                self.assertEqual(result.state,"candidate")
                self.assertEqual(row,original)
                meta = json.loads(result.candidate["metadata_json"])
                self.assertEqual(meta["pin_type"],"relative" if relative else "absolute")
                self.assertEqual(meta["retained_material_gain_cp"],300)
                self.assertEqual(meta["evaluation_player_cp"]["pin"],300)
                self.assertEqual(result.candidate["solution_line"]," ".join(sans))
                self.assertEqual(meta["classification"],"wins_pinned_piece")
                self.assertEqual({c.args[1] for c in service.position.call_args_list},{"tactic_quick_v1","tactic_verify_v1"})

    def test_relative_blocker_moves_and_original_pinner_wins_target(self):
        row, evaluate, _, _ = proof_fixture(relative=True,exposed=True)
        result = analyze_single_move(row,evaluate)
        self.assertEqual(result.state,"candidate")
        meta = json.loads(result.candidate["metadata_json"])
        self.assertEqual(meta["classification"],"blocker_moves_target_lost")
        self.assertEqual(meta["retained_material_gain_cp"],900)

    def test_geometry_without_value_or_capture_is_not_candidate(self):
        row, evaluate, fens, _ = proof_fixture()
        flat = lambda fen, profile: {**evaluate(fen,profile),"score_cp":0}
        self.assertEqual(analyze_single_move(row,flat).state,"analyzed_no_hit")
        def quiet(fen,profile):
            raw = evaluate(fen,profile)
            if fen == fens[1]:
                raw["principal_variation"] = "a6 Kh2"
            return raw
        self.assertEqual(analyze_single_move(row,quiet).state,"analyzed_no_hit")

    def test_recapture_or_unsustained_eval_rejects_apparent_win(self):
        row, evaluate, fens, _ = proof_fixture()
        def losing(fen, profile):
            raw = evaluate(fen,profile)
            if fen == fens[-1]:
                raw["score_cp"] = -500
            return raw
        self.assertEqual(analyze_single_move(row,losing).state,"analyzed_no_hit")
        # Without the d2 pawn, Kxc3 legally recaptures the bishop: knight-for-
        # bishop is no retained material gain, regardless of inflated fake eval.
        board = chess.Board(ABSOLUTE_FEN.replace("3P4","8"))
        unprotected = move_row(board.fen(),"h1h2")
        board.push_uci("c1b2")
        pin_fen = board.fen()
        board.push_uci("a7a6")
        board.push_uci("b2c3")
        cap_fen = board.fen()
        def recaptured(fen,profile):
            return {"score_pov":"white","score_type":"cp","score_cp":0 if fen==unprotected["fen_after"] else 300,
                    "principal_variation":"a6 Bxc3+" if fen==pin_fen else "Kxc3" if fen==cap_fen else ""}
        self.assertEqual(analyze_single_move(unprotected,recaptured).state,"analyzed_no_hit")

    def test_missing_proof_mate_and_illegal_pv(self):
        row, evaluate, fens, _ = proof_fixture()
        for pv in ("", "a6"):
            def short(fen,profile):
                raw = evaluate(fen,profile)
                if fen==fens[1]:
                    raw["principal_variation"] = pv
                return raw
            self.assertEqual(analyze_single_move(row,short).state,"analyzed_no_hit")
        def bad(fen,profile):
            raw = evaluate(fen,profile)
            if fen==fens[1]:
                raw["principal_variation"] = "Qa9 Bxc3"
            return raw
        with self.assertRaises(ValueError):
            analyze_single_move(row,bad)
        def mate(fen,profile):
            return {"score_pov":"white","score_type":"mate","mate":2,"score_cp":None}
        self.assertEqual(analyze_single_move(row,mate).state,"analyzed_no_hit")

    def test_dispatch_failure_is_error_and_no_persistence(self):
        row, _, _, _ = proof_fixture()
        with closing(sqlite3.connect(":memory:")) as connection:
            with patch("analysis_engine.PositionAnalysisService.position",side_effect=RuntimeError("engine failed")):
                result = dispatch_heavy(ANALYZERS["missed_pin"],connection,None,row,Counter())
            self.assertEqual(result.state,"error")
            self.assertEqual(connection.total_changes,0)

    def test_pin_versions_and_existing_fork_mate_definitions_unchanged(self):
        pin = ANALYZERS["missed_pin"]
        self.assertEqual((pin.screener_version,pin.scout_version,pin.analyzer_version),("1","1","2"))
        for key, screen, version in (("missed_fork","2","2"),("missed_mate","0","3")):
            definition = ANALYZERS[key]
            self.assertEqual((definition.screener_version,definition.analyzer_version),(screen,version))
            self.assertEqual(coverage_decision(definition,{"coverage_status":"candidate","screener_version":"0",
                             "analyzer_version":version,"scout_version":"0","scout_config":""}),"current")


class MaterialTests(unittest.TestCase):
    def test_material_policy_is_injected_and_orientation_reverses(self):
        board = chess.Board("7k/8/8/8/8/8/8/Q6K w - - 0 1")
        self.assertEqual(material_balance(board,chess.WHITE,PIECE_VALUES),900)
        self.assertEqual(material_balance(board,chess.BLACK,PIECE_VALUES),-900)
        self.assertEqual(material_balance(board,chess.WHITE,{chess.KING:0,chess.QUEEN:10}),10)
        with self.assertRaises(KeyError):
            material_balance(board,chess.WHITE,{chess.KING:0})


class PinRepositoryTests(unittest.TestCase):
    def test_pin_candidate_reuses_canonical_id_training_and_second_run_is_noop(self):
        fixture = repository_fixtures.RepositoryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.seed_old_candidate()
        connection = fixture.c
        connection.execute("UPDATE tactic_candidates SET tactic_type='missed_pin',detector_version=0 WHERE candidate_id=42")
        connection.commit()
        row, evaluate, _, _ = proof_fixture()
        result = analyze_single_move(row,evaluate)
        # Keep this V1 persistence regression explicitly on its baseline version.
        definition = replace(ANALYZERS["missed_pin"], analyzer_version="1", heavy=pin_adapter)
        allowed = {(1,"missed_pin")}
        saved = save_heavy_result(connection,definition,row,result,allowed,coverage_decision)
        self.assertEqual(saved["action"],"candidate_updated")
        self.assertEqual(saved["candidate_id"],42)
        self.assertEqual(tuple(connection.execute("SELECT * FROM training_attempts").fetchone()),(1,42))
        self.assertEqual(connection.execute("SELECT created_at FROM tactic_candidates").fetchone()[0],"original")
        changed = connection.total_changes
        self.assertEqual(save_heavy_result(connection,definition,row,result,allowed,coverage_decision)["action"],"unchanged")
        self.assertEqual(connection.total_changes,changed)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM tactic_candidates").fetchone()[0],1)


if __name__ == "__main__":
    unittest.main()
