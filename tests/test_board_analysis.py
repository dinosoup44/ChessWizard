from dataclasses import FrozenInstanceError
import unittest

import chess

from board_analysis import (
    direction, ray_squares, between_squares, neighborhood, attack_map,
    attacked_pieces, attacked_squares, attackers, line_relationship, ray_contacts,
    piece_safety, legal_mobility, capture_square, king_safety,
)
from analyze_forks_v2 import get_fork_targets, get_capture_square
from tactic_screeners import enemy_targets_after_move


class GeometryTests(unittest.TestCase):
    def test_alignment_and_between_order(self):
        self.assertEqual(direction(chess.A1, chess.H8), (1, 1))
        self.assertEqual(direction(chess.H8, chess.A1), (-1, -1))
        self.assertIsNone(direction(chess.A1, chess.B3))
        self.assertIsNone(direction(chess.A1, chess.A1))
        self.assertEqual(between_squares(chess.A4, chess.A1), (chess.A3, chess.A2))
        self.assertEqual(between_squares(chess.A1, chess.A2), ())
        self.assertEqual(between_squares(chess.A1, chess.B3), ())

    def test_rays_do_not_wrap_and_neighborhood_stays_on_board(self):
        self.assertEqual(ray_squares(chess.H1, (1, 0)), ())
        self.assertEqual(ray_squares(chess.F6, (1, 1)), (chess.G7, chess.H8))
        self.assertEqual(neighborhood(chess.A1), (chess.B1, chess.A2, chess.B2))
        self.assertEqual(neighborhood(chess.D4, 0), ())
        with self.assertRaises(ValueError):
            ray_squares(chess.A1, (0, 0))
        with self.assertRaises(ValueError):
            neighborhood(chess.A1, -1)


class AttackAndSafetyTests(unittest.TestCase):
    def test_pawn_push_is_not_attack_and_friendly_piece_is_defended(self):
        board = chess.Board("7k/8/8/8/8/3NP3/8/7K w - - 0 1")
        self.assertEqual(attacked_squares(board, chess.E3), (chess.D4, chess.F4))
        board.set_piece_at(chess.D4, chess.Piece(chess.BISHOP, chess.WHITE))
        self.assertIn(chess.E3, piece_safety(board, chess.D4).defenders)
        self.assertEqual([p.square for p in attacked_pieces(board, chess.E3, target_color=chess.WHITE)], [chess.D4])
        self.assertEqual(attacked_pieces(board, chess.E3, piece_types=()), ())

    def test_pinned_piece_attacks_but_cannot_move(self):
        board = chess.Board("4r1k1/8/8/8/5q2/8/4N3/4K3 w - - 0 1")
        self.assertIn(chess.E2, attackers(board, chess.F4, chess.WHITE))
        self.assertEqual(legal_mobility(board, chess.E2).move_count, 0)
        pinned = piece_safety(board, chess.E2)
        self.assertTrue(pinned.absolutely_pinned)
        self.assertEqual(pinned.pin_line, tuple(chess.SquareSet(chess.BB_FILE_E)))
        queen = piece_safety(board, chess.F4)
        self.assertTrue(queen.attacked_and_undefended)
        self.assertIsNone(piece_safety(board, chess.A1))
        with self.assertRaises(FrozenInstanceError):
            queen.absolutely_pinned = True

    def test_sliding_attacks_stop_at_first_blocker_and_map_collects_sources(self):
        board = chess.Board("7k/q7/8/8/8/p7/8/R6K w - - 0 1")
        self.assertIn(chess.A3, attacked_squares(board, chess.A1))
        self.assertNotIn(chess.A7, attacked_squares(board, chess.A1))
        mapping = attack_map(board, chess.WHITE)
        self.assertEqual(mapping.sources_by_target[chess.A3], (chess.A1,))
        self.assertIn(chess.A3, mapping.attacked_squares)
        self.assertEqual(attacked_squares(board, chess.D4), ())


class LineTests(unittest.TestCase):
    def test_blockers_and_xray_contacts_are_ordered_without_claiming_attack(self):
        board = chess.Board("7k/q7/8/8/8/p7/8/R6K w - - 0 1")
        line = line_relationship(board, chess.A1, chess.A7)
        self.assertEqual([p.square for p in line.blockers], [chess.A3])
        self.assertFalse(line.clear)
        contacts = ray_contacts(board, chess.A1, (0, 1))
        self.assertEqual([c.piece.square for c in contacts], [chess.A3, chess.A7])
        self.assertEqual(contacts[0].intervening, ())
        self.assertEqual(contacts[1].intervening, (contacts[0].piece,))
        self.assertTrue(line_relationship(board, chess.A1, chess.A3).clear)
        self.assertFalse(line_relationship(board, chess.A1, chess.B3).clear)
        self.assertFalse(line_relationship(board, chess.A1, chess.A1).clear)


class MobilityAndKingTests(unittest.TestCase):
    def test_initial_mobility_only_describes_side_to_move(self):
        board = chess.Board()
        self.assertEqual(legal_mobility(board).move_count, 20)
        self.assertEqual(legal_mobility(board, chess.B1).moves_uci, ("b1a3", "b1c3"))
        self.assertEqual(legal_mobility(board, chess.B8).move_count, 0)
        self.assertIsNone(king_safety(board, chess.BLACK).legal_moves_uci)
        self.assertEqual(king_safety(board, chess.WHITE).pawn_shield, (chess.D2, chess.E2, chess.F2))

    def test_en_passant_capture_square_both_colors(self):
        board = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        for position, uci, square in ((board, "e5d6", chess.D5), (board.mirror(), "e4d3", chess.D4)):
            move = chess.Move.from_uci(uci)
            self.assertIn(uci, legal_mobility(position).captures_uci)
            self.assertEqual(capture_square(position, move), square)
            self.assertEqual(get_capture_square(position, move), square)
        self.assertIsNone(capture_square(board, chess.Move.from_uci("e1f1")))

    def test_pinned_en_passant_is_not_legal_mobility(self):
        board = chess.Board("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        self.assertNotIn("e5d6", legal_mobility(board).moves_uci)

    def test_promotions_are_four_moves_to_one_destination(self):
        board = chess.Board("7k/P7/8/8/8/8/8/7K w - - 0 1")
        mobility = legal_mobility(board, chess.A7)
        self.assertEqual(mobility.moves_uci, ("a7a8b", "a7a8n", "a7a8q", "a7a8r"))
        self.assertEqual(mobility.destinations, (chess.A8,))

    def test_castling_is_legal_king_mobility(self):
        board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertIn("e1g1", king_safety(board, chess.WHITE).legal_moves_uci)
        self.assertIn("e1c1", king_safety(board, chess.WHITE).legal_moves_uci)

    def test_king_vacating_square_exposes_ray_even_if_destination_not_currently_attacked(self):
        board = chess.Board("k3r3/8/8/8/8/8/4K3/8 w - - 0 1")
        safety = king_safety(board, chess.WHITE)
        self.assertEqual(safety.checking_pieces, (chess.E8,))
        self.assertNotIn(chess.E1, safety.attacked_zone)
        self.assertNotIn("e2e1", safety.legal_moves_uci)
        self.assertIn("e2d1", safety.legal_moves_uci)

    def test_missing_king_and_checkmate(self):
        self.assertIsNone(king_safety(chess.Board.empty(), chess.WHITE))
        board = chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
        self.assertTrue(board.is_checkmate())
        self.assertEqual(king_safety(board, chess.BLACK).legal_moves_uci, ())


class IntegrationTests(unittest.TestCase):
    def test_fork_adapters_keep_target_schema_values_and_order_for_both_colors(self):
        board = chess.Board("r3k3/2N5/8/8/8/8/8/4K3 b - - 0 1")
        for position, source, color, expected in (
            (board, chess.C7, chess.WHITE, [("a8", chess.ROOK, 500), ("e8", chess.KING, 10000)]),
            (board.mirror(), chess.C2, chess.BLACK, [("a1", chess.ROOK, 500), ("e1", chess.KING, 10000)]),
        ):
            heavy = get_fork_targets(position, source, color)
            screen = enemy_targets_after_move(position, source, color)
            self.assertEqual([(t["square"], t["piece_type"], t["value"]) for t in heavy], expected)
            self.assertEqual(screen, [{k: v for k, v in t.items() if k != "piece"} for t in heavy])
            self.assertEqual([t["piece"] for t in heavy], ["rook", "king"])

    def test_primitives_leave_board_history_and_results_unchanged(self):
        board = chess.Board()
        for san in ("e4", "d5", "exd5", "Qxd5"):
            board.push_san(san)
        before = (board.fen(en_passant="fen"), tuple(board.move_stack), board.chess960)
        mapping = attack_map(board, board.turn)
        piece_safety(board, chess.D5)
        line_relationship(board, chess.D1, chess.D5)
        ray_contacts(board, chess.D1, (0, 1))
        attacked_pieces(board, chess.D5)
        legal_mobility(board)
        king_safety(board, chess.WHITE)
        king_safety(board, chess.BLACK)
        self.assertEqual((board.fen(en_passant="fen"), tuple(board.move_stack), board.chess960), before)
        board.clear()
        self.assertTrue(mapping.attacked_squares)  # Result is detached from mutable Board.


if __name__ == "__main__":
    unittest.main()
