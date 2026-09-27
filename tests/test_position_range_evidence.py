from dataclasses import FrozenInstanceError, asdict
import ast
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch
import chess
from position_range_evidence import (LegalReplay, IllegalRangeError, analyze_range,
    analyze_position, terminal_state, SideMaterial)


class MaterialAndIdentityTests(unittest.TestCase):
    def test_quiet_empty_capture_and_snapshots(self):
        empty = analyze_range(chess.STARTING_FEN, (), material_snapshots=True)
        self.assertEqual(empty.start_fen, empty.end_fen)
        self.assertEqual(empty.material_transition.snapshots, (SideMaterial(3900, 3900),))
        self.assertIsNone(empty.attacker_survival)
        one = analyze_range(chess.STARTING_FEN, ['e2e4'])
        self.assertEqual(one.ply_count, 1)
        self.assertEqual(one.material_transition.delta, SideMaterial(0, 0))
        result = analyze_range(chess.STARTING_FEN, ['e2e4', 'd7d5', 'e4d5'],
                               track_squares=['d7'], material_snapshots=True)
        material = result.material_transition
        self.assertEqual(material.delta, SideMaterial(0, -100))
        self.assertEqual(material.captured_by_side, SideMaterial(100, 0))
        self.assertEqual(material.lost_by_side, SideMaterial(0, 100))
        self.assertEqual(len(material.snapshots), 4)
        target = result.tracked_piece_fates[0]
        self.assertFalse(target.alive)
        self.assertEqual(target.capture_ply, 3)
        self.assertEqual(target.captured_by.initial_square, chess.E2)
        self.assertEqual(target.move_count, 1)
        self.assertTrue(result.attacker_survival.moved_again)
        self.assertEqual(result.attacker_survival.destination_after_tactic, chess.E4)

    def test_en_passant_victim_is_not_destination(self):
        result = analyze_range('7k/8/8/3pP3/8/8/8/7K w - d6 0 2', ['e5d6'], track_squares=['d5'])
        c = result.material_transition.captures[0]
        self.assertTrue(c.en_passant)
        self.assertEqual((c.square, c.destination), (chess.D5, chess.D6))
        self.assertEqual(result.tracked_piece_fates[0].capture_ply, 1)

    def test_all_promotions_and_capture_promotions(self):
        for promoted, value in [('q', 900), ('r', 500), ('b', 300), ('n', 300)]:
            for capture in [False, True]:
                with self.subTest(promoted=promoted, capture=capture):
                    fen = '1r5k/P7/8/8/8/8/8/7K w - - 0 1'
                    move = 'a7' + ('b8' if capture else 'a8') + promoted
                    e = analyze_range(fen, [move], track_squares=['a7'])
                    fate = e.tracked_piece_fates[0]
                    self.assertEqual(fate.piece.initial_piece_type, chess.PAWN)
                    self.assertTrue(fate.promoted)
                    self.assertEqual(fate.final_piece_type, chess.PIECE_SYMBOLS.index(promoted))
                    self.assertEqual(e.material_transition.promotion_delta.white, value - 100)
                    self.assertEqual(e.material_transition.delta.black, -500 if capture else 0)

    def test_promoted_identity_captured_and_second_queen_distinct(self):
        replay = LegalReplay('1r5k/P7/8/8/8/8/8/1Q5K w - - 0 1', ['a7a8q', 'b8a8'])
        e = replay.evidence(track_squares=['a7', 'b1'])
        pawn, queen = e.tracked_piece_fates
        self.assertNotEqual(pawn.piece, queen.piece)
        self.assertFalse(pawn.alive)
        self.assertTrue(queen.alive)
        self.assertEqual(pawn.capture_ply, 2)
        self.assertEqual(e.material_transition.captures[0].victim_type, chess.QUEEN)
        self.assertEqual(pawn.final_piece_type, chess.QUEEN)
        self.assertEqual(replay.position_evidence(ply=1, squares=['a8']).attack_states[0].piece, pawn.piece)

    def test_identical_rook_replacement_and_knight_identity(self):
        e = analyze_range('7k/8/8/8/8/8/8/R1R4K w - - 0 1',
            ['a1a2', 'h8g8', 'c1a1', 'g8h8', 'a2c2', 'h8g8', 'c2c1'], track_squares=['a1', 'c1'])
        first, second = e.tracked_piece_fates
        self.assertEqual((first.current_square, second.current_square), (chess.C1, chess.A1))
        self.assertEqual((first.move_count, second.move_count), (3, 1))
        e = analyze_range('7k/8/8/8/8/8/8/1N4NK w - - 0 1',
            ['b1c3', 'h8g8', 'g1f3', 'g8h8', 'c3b1'], track_squares=['b1', 'g1'])
        self.assertEqual([f.current_square for f in e.tracked_piece_fates], [chess.B1, chess.F3])

    def test_castling_both_sides_and_colors(self):
        for color in ['w', 'b']:
            for kingmove, rook, destination in [('e1g1', 'h1', 'f1'), ('e1c1', 'a1', 'd1')]:
                if color == 'b':
                    kingmove, rook, destination = kingmove.replace('1', '8'), rook.replace('1', '8'), destination.replace('1', '8')
                replay = LegalReplay(f'r3k2r/8/8/8/8/8/8/R3K2R {color} KQkq - 0 1', [kingmove])
                e = replay.evidence(track_squares=[rook])
                self.assertEqual(e.tracked_piece_fates[0].current_square, chess.parse_square(destination))
                self.assertEqual(e.material_transition.delta, SideMaterial(0, 0))
                self.assertEqual(e.material_transition.captures, ())
                self.assertEqual(replay.position_evidence(ply=0, squares=[rook]).attack_states[0].piece,
                                 replay.identity_at_start(rook))

    def test_chess960_overlap_and_stationary_castlers(self):
        cases = [('1R1K1R2', 'FB', 'd1f1', 'f1', 'f1', 'g1'),
                 ('1R1K1R2', 'FB', 'd1b1', 'b1', 'd1', 'c1'),
                 ('5KR1', 'G', 'f1g1', 'g1', 'f1', 'g1'),
                 ('6KR', 'H', 'g1h1', 'h1', 'f1', 'g1')]
        for pieces, rights, move, rook, rook_end, king_end in cases:
            with self.subTest(move=move):
                board = chess.Board(f'4k3/8/8/8/8/8/8/{pieces} w {rights} - 0 1', chess960=True)
                replay = LegalReplay(board, [move])
                e = replay.evidence(track_squares=[rook])
                self.assertEqual(e.tracked_piece_fates[0].current_square, chess.parse_square(rook_end))
                self.assertEqual(e.attacker_survival.destination_after_tactic, chess.parse_square(king_end))
                self.assertEqual(e.material_transition.captures, ())
                self.assertEqual(e.tracked_piece_fates[0].move_count, 1)
                self.assertEqual(replay.board_at(0).fen(), board.fen())
                self.assertEqual(replay.position_evidence(ply=0, squares=[rook]).attack_states[0].piece,
                                 replay.identity_at_start(rook))

    def test_shared_and_custom_values_are_isolated(self):
        values = {1: 10, 2: 32, 3: 33, 4: 51, 5: 99, 6: 0}
        replay = LegalReplay('1r5k/P7/8/8/8/8/8/7K w - - 0 1', ['a7b8q'], piece_values=values)
        values[5] = 999
        e = replay.evidence()
        self.assertEqual(e.material_transition.delta, SideMaterial(89, -51))
        for bad in [{}, {1: -1}, {i: 1.5 for i in range(1, 7)}]:
            with self.assertRaises(ValueError):
                LegalReplay(chess.STARTING_FEN, (), piece_values=bad)


class AttacksAndRecaptureTests(unittest.TestCase):
    def test_geometric_pinned_attacker_has_no_legal_capture(self):
        board = chess.Board('4r1k1/8/8/8/5q2/8/4N3/4K3 w - - 0 1')
        state = analyze_position(board, squares=['f4']).attack_states[0]
        self.assertTrue(state.attacked)
        self.assertIn(chess.E2, state.geometric_attackers)
        self.assertIn(chess.E2, state.pinned_geometric_sources)
        self.assertEqual(state.legal_attackers, ())
        self.assertFalse(state.legal_capture_available)
        replay = LegalReplay(board, ())
        self.assertEqual(replay.relevant_recaptures(track_squares=['f4']), ())

    def test_defense_and_multiple_attacks_and_empty_control(self):
        state = analyze_position('7k/8/8/8/3r4/2B1B3/3R4/7K w - - 0 1',
                                 squares=['d4', 'd2', 'b4']).attack_states
        self.assertEqual(state[0].attacker_count, 3)
        self.assertEqual(len(state[0].legal_attackers), 3)
        self.assertIsNone(state[1].legal_attackers)
        self.assertEqual(state[1].legal_capture_reason, 'opponent_not_to_move')
        self.assertIsNone(state[2].attacked)
        self.assertIn(chess.C3, state[2].white_control_sources)
        defended = analyze_position('7k/8/8/8/8/3RP3/8/7K w - - 0 1', squares=['d3']).attack_states[0]
        self.assertFalse(defended.defended)
        defended = analyze_position('7k/8/8/8/3R4/4P3/8/7K w - - 0 1', squares=['d4']).attack_states[0]
        self.assertTrue(defended.defended)
        self.assertEqual(defended.defender_count, 1)

    def test_king_control_and_checked_king(self):
        state = analyze_position('7k/8/8/8/8/2n5/1K6/8 w - - 0 1', squares=['c3']).attack_states[0]
        self.assertIn(chess.B2, state.legal_attackers)
        e = analyze_range('7k/8/8/8/8/8/r7/K7 w - - 0 1', [], track_squares=['a1'])
        self.assertTrue(e.tracked_piece_fates[0].is_checked_king)
        self.assertTrue(e.tracked_piece_fates[0].attack_state.side_to_move_in_check)

    def test_en_passant_legal_capture_square_and_exposed_king(self):
        legal = analyze_position('7k/8/8/3pP3/8/8/8/7K w - d6 0 2', squares=['d5', 'e5']).attack_states
        self.assertEqual(legal[0].geometric_attackers, ())
        self.assertEqual(legal[0].legal_attackers, (chess.E5,))
        self.assertEqual(legal[1].legal_capture_squares, (chess.D5,))
        illegal = analyze_position('7k/8/8/r2pP2K/8/8/8/8 w - d6 0 2', squares=['d5']).attack_states[0]
        self.assertFalse(illegal.legal_capture_available)
        with self.assertRaises(IllegalRangeError):
            LegalReplay('7k/8/8/r2pP2K/8/8/8/8 w - d6 0 2', ['e5d6'])

    def test_immediate_recapture_and_intermediate_original_identity(self):
        replay = LegalReplay(chess.STARTING_FEN, ['e2e4', 'd7d5', 'e4d5', 'd8d5'])
        options = replay.relevant_recaptures(ply=3, track_squares=['d7'])
        q = next(o for o in options if o.capture.uci == 'd8d5')
        self.assertIn('captures_attacker', q.relations)
        self.assertIn('onto_recent_capture_square', q.relations)
        self.assertEqual(q.capture.victim, replay.identity_at_start('e2'))
        self.assertEqual(q.capture.san, 'Qxd5')
        self.assertFalse(q.capture.side_to_move)
        e = replay.evidence(track_squares=['d7'])
        self.assertFalse(e.attacker_survival.fate.alive)
        self.assertEqual(e.attacker_survival.fate.capture_ply, 4)

    def test_blocker_removal_exposes_capture_without_predicting_play(self):
        replay = LegalReplay('7k/8/8/8/n7/b7/8/R6K b - - 0 1', ['a3b4'])
        self.assertEqual(replay.relevant_recaptures(ply=0, track_squares=['a4']), ())
        options = replay.relevant_recaptures(track_squares=['a4'])
        capture = next(o for o in options if o.capture.uci == 'a1a4')
        self.assertIn('captures_target', capture.relations)
        self.assertEqual(capture.capture.victim.initial_square, chess.A4)

    def test_en_passant_landing_square_recapture_and_explicit_lookback(self):
        replay = LegalReplay('7k/2p5/8/3pP3/8/8/8/7K w - d6 0 2', ['e5d6'])
        options = replay.relevant_recaptures()
        option = next(o for o in options if o.capture.uci == 'c7d6')
        self.assertIn('onto_recent_capture_square', option.relations)
        self.assertIn('captures_attacker', option.relations)
        without_recency = replay.relevant_recaptures(lookback_plies=0)
        option = next(o for o in without_recency if o.capture.uci == 'c7d6')
        self.assertNotIn('onto_recent_capture_square', option.relations)
        self.assertIn('captures_attacker', option.relations)

    def test_multiple_and_no_recaptures_with_explicit_recency(self):
        replay = LegalReplay('7k/8/8/8/3r4/2B1B3/3R4/7K w - - 0 1', ())
        options = replay.relevant_recaptures(track_squares=['d4'])
        self.assertEqual(len(options), 3)
        self.assertTrue(all(o.capture.legal for o in options))
        self.assertEqual(LegalReplay(chess.STARTING_FEN, ['e2e4']).relevant_recaptures(), ())
        with self.assertRaises(ValueError):
            replay.relevant_recaptures(lookback_plies=-1)


class TerminalTests(unittest.TestCase):
    def test_mate_stalemate_and_insufficient(self):
        cases = [('7k/6Q1/5K2/8/8/8/8/8 b - - 0 1', 'checkmate'),
                 ('7k/5K2/6Q1/8/8/8/8/8 b - - 0 1', 'stalemate'),
                 ('7k/8/8/8/8/8/8/7K w - - 0 1', 'insufficient_material')]
        for fen, state in cases:
            result = terminal_state(chess.Board(fen))
            self.assertEqual(result.state, state)
            self.assertTrue(result.is_terminal)
            self.assertTrue(result.determined_from_position_alone)
            self.assertEqual(result.winner, True if state == 'checkmate' else None)

    def test_unknown_history_and_complete_start(self):
        self.assertEqual(analyze_position(chess.STARTING_FEN).terminal_state.state, 'nonterminal')
        board = chess.Board(); board.push_uci('g1f3')
        self.assertEqual(terminal_state(board).state, 'nonterminal')
        unknown = terminal_state(chess.Board(board.fen()))
        self.assertEqual(unknown.state, 'unknown_history_dependent')
        self.assertIsNone(unknown.repetition_claimable)
        self.assertFalse(unknown.is_terminal)
        self.assertEqual(terminal_state(chess.Board(board.fen()), history_complete=True).state, 'nonterminal')

    def test_claimable_repetition_is_not_automatic_draw_and_history_preserved(self):
        board = chess.Board()
        for move in ['g1f3', 'g8f6', 'f3g1', 'f6g8'] * 2:
            board.push_uci(move)
        original = (board.fen(), tuple(board.move_stack))
        result = terminal_state(board)
        self.assertEqual(result.state, 'repetition_claimable')
        self.assertFalse(result.is_terminal)
        self.assertFalse(result.determined_from_position_alone)
        self.assertEqual(original, (board.fen(), tuple(board.move_stack)))
        self.assertIsNone(terminal_state(chess.Board(board.fen())).repetition_claimable)
        for move in ['g1f3', 'g8f6', 'f3g1', 'f6g8'] * 2:
            board.push_uci(move)
        self.assertEqual(terminal_state(board).draw_reason, 'fivefold_repetition')
        self.assertTrue(terminal_state(board).is_terminal)

    def test_repetition_claim_on_intended_move_and_explicit_history_validation(self):
        board = chess.Board()
        for move in ['g1f3', 'g8f6', 'f3g1', 'f6g8', 'g1f3', 'g8f6', 'f3g1']:
            board.push_uci(move)
        state = terminal_state(board)
        self.assertEqual(state.state, 'repetition_claimable')
        self.assertFalse(board.is_repetition(3))
        with self.assertRaises(ValueError):
            terminal_state(board, history_complete='yes')
        with self.assertRaises(ValueError):
            terminal_state(chess.Board.empty())

    def test_fifty_claim_and_automatic_seventyfive(self):
        for clock in (99, 100):
            state = terminal_state(chess.Board(f'7k/8/8/8/8/8/8/R6K w - - {clock} 70'))
            self.assertEqual(state.state, 'fifty_move_claimable')
            self.assertFalse(state.is_terminal)
            self.assertTrue(state.determined_from_position_alone)
        state = terminal_state(chess.Board('7k/8/8/8/8/8/8/R6K w - - 150 80'))
        self.assertEqual(state.draw_reason, 'seventyfive_moves')
        self.assertTrue(state.is_terminal)
        mate = terminal_state(chess.Board('7k/6Q1/5K2/8/8/8/8/8 b - - 150 80'))
        self.assertEqual(mate.state, 'checkmate')


class ReplayContractTests(unittest.TestCase):
    def test_invalid_input_fails_cleanly_and_source_unchanged(self):
        board = chess.Board()
        for moves, sans in [(['e2e4', 'e7e4'], None), (['0000'], None),
                            (['e2e4'], ['d4']), (['e2e4'], ['e4#']), (['e2e4'], []), (['garbage'], None)]:
            with self.subTest(moves=moves, sans=sans):
                with self.assertRaises(IllegalRangeError):
                    LegalReplay(board, moves, moves_san=sans)
                self.assertEqual(board.fen(), chess.STARTING_FEN)
                self.assertFalse(board.move_stack)
        with self.assertRaisesRegex(IllegalRangeError, 'ply 2'):
            LegalReplay(board, ['e2e4', 'e7e4'])
        with self.assertRaises(ValueError):
            LegalReplay(chess.Board.empty(), ())
        replay = LegalReplay(board, [])
        with self.assertRaises(KeyError):
            replay.identity_at_start('e4')
        with self.assertRaises(ValueError):
            replay.board_at(-1)
        with self.assertRaises(ValueError):
            replay.position_evidence(squares=[64])

    def test_source_result_and_returned_board_are_isolated(self):
        board = chess.Board(); board.push_uci('e2e4')
        before = (board.fen(), tuple(board.move_stack))
        replay = LegalReplay(board, ['e7e5'])
        e = replay.evidence(track_squares=['e4'])
        copy = replay.board_at(); copy.clear()
        board.clear()
        self.assertEqual(replay.board_at(0).fen(), before[0])
        self.assertNotEqual(replay.board_at().fen(), copy.fen())
        with self.assertRaises(FrozenInstanceError):
            e.end_fen = 'changed'
        self.assertEqual(asdict(e), asdict(replay.evidence(track_squares=['e4'])))
        self.assertEqual(e.get_piece_fate(replay.identity_at_start('e4')).piece.initial_square, chess.E4)

    def test_long_random_legal_ranges_independent_material_identity_and_legality(self):
        rng = random.Random(910)
        for _ in range(8):
            board = chess.Board(); moves = []
            for _ in range(80):
                legal = list(board.legal_moves)
                if not legal:
                    break
                move = rng.choice(legal); moves.append(move.uci()); board.push(move)
            replay = LegalReplay(chess.STARTING_FEN, moves)
            e = replay.evidence(track_squares=range(8, 16), material_snapshots=True)
            self.assertEqual(e.end_fen, board.fen())
            values = dict(e.material_transition.piece_values)
            independent = chess.Board()
            identities = {s: replay.identity_at_start(s) for s in independent.piece_map()}
            captured = set()
            for event in e.moves:
                move = chess.Move.from_uci(event.uci)
                self.assertTrue(independent.is_legal(move))
                if event.capture:
                    self.assertEqual(independent.piece_type_at(event.capture.square), event.capture.victim_type)
                    self.assertNotIn(event.capture.victim, captured)
                    captured.add(event.capture.victim)
                for transition in event.transitions:
                    self.assertEqual(identities.pop(transition.from_square), transition.piece)
                for transition in event.transitions:
                    if transition.to_square is not None:
                        self.assertNotIn(transition.piece, captured)
                        identities[transition.to_square] = transition.piece
                independent.push(move)
                self.assertEqual(set(identities), set(independent.piece_map()))
                self.assertEqual(len(set(identities.values())), len(identities))
                totals = SideMaterial(*(sum(values[p.piece_type] for p in independent.piece_map().values()
                                             if p.color == c) for c in (True, False)))
                self.assertEqual(e.material_transition.snapshots[event.ply], totals)
            selected = list(board.piece_map())[:6]
            states = replay.position_evidence(squares=selected).attack_states
            for state in states:
                if state.legal_capture_reason == 'evaluated_for_actual_side_to_move':
                    expected = {m.from_square for m in board.legal_moves if board.is_capture(m) and (
                        (m.to_square + (-8 if board.turn else 8)) if board.is_en_passant(m) else m.to_square) == state.square}
                    self.assertEqual(set(state.legal_attackers), expected)
            self.assertEqual(e.material_transition.delta.white,
                             e.material_transition.promotion_delta.white - e.material_transition.lost_by_side.white)

    def test_no_eager_attack_maps_and_no_external_io(self):
        with patch('position_range_evidence.replay.attack_state', side_effect=AssertionError('unrequested')):
            analyze_position(chess.STARTING_FEN)
        with patch('sqlite3.connect', side_effect=AssertionError('DB')), \
             patch('subprocess.Popen', side_effect=AssertionError('engine/process')):
            analyze_range(chess.STARTING_FEN, ['e2e4', 'd7d5', 'e4d5'], track_squares=['d7'])
        forbidden = ('tkinter', 'sqlite3', 'subprocess', 'chess.engine', 'engine_cache', 'database', 'fork', 'pin_adapter')
        for path in (Path(__file__).resolve().parents[1] / 'position_range_evidence').glob('*.py'):
            tree = ast.parse(path.read_text())
            imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(name.startswith(forbidden) for name in imports), path.name)


if __name__ == '__main__':
    unittest.main()
