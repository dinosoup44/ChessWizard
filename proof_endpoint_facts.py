"""Legal replay facts for audits; no settlement, motif admission, engine or storage policy."""
from dataclasses import asdict
import chess
from board_analysis import capture_square, material_balance
from proof_evidence_state import terminal_facts


def collect_endpoint_facts(fen_before, tactic_uci, continuation, targets, piece_values, *, endpoint_evaluation=None):
    """Track original piece identities and material from before the tactic.

    Attacker captures of original targets are a geometric ledger, not causal credit.
    Legal recaptures are possibilities, not evidence that best defense selects them.
    """
    board = chess.Board(fen_before)
    player = board.turn
    initial = material_balance(board, player, piece_values)
    root = board.parse_uci(tactic_uci)
    attacker = root.from_square
    target_locations = {chess.parse_square(s): chess.parse_square(s) for s in targets}
    captures, balances, moves = [], [initial], []
    target_capture_cp = 0
    last_capture_destination = None
    for ply, uci in enumerate((tactic_uci, *continuation)):
        move = board.parse_uci(uci)
        square = capture_square(board, move)
        victim = board.piece_at(square) if square is not None else None
        san = board.san(move)
        forcing = board.is_check() or victim is not None or bool(move.promotion) or board.gives_check(move)
        target_hit = next((original for original, current in target_locations.items() if current == square), None) if square is not None else None
        if victim:
            credited = board.turn == player and move.from_square == attacker and target_hit is not None
            signed = piece_values[victim.piece_type] * (1 if board.turn == player else -1)
            target_capture_cp += signed if credited else 0
            captures.append({'ply':ply, 'san':san, 'square':chess.square_name(square),
                'victim':victim.symbol(), 'signed_cp':signed, 'original_target':chess.square_name(target_hit) if target_hit is not None else None,
                'by_original_attacker':move.from_square == attacker})
        for original, current in list(target_locations.items()):
            if current is not None and current == square:
                target_locations[original] = None
            elif current == move.from_square:
                target_locations[original] = move.to_square
            elif current is not None and board.is_castling(move) and board.piece_at(current) == chess.Piece(chess.ROOK, board.turn):
                rank = chess.square_rank(move.from_square)
                kingside = board.is_kingside_castling(move)
                if current == chess.square(7 if kingside else 0, rank):
                    target_locations[original] = chess.square(5 if kingside else 3, rank)
        if attacker is not None and attacker == square:
            attacker = None
        elif attacker == move.from_square:
            attacker = move.to_square
        last_capture_destination = move.to_square if victim else None
        board.push(move)
        balances.append(material_balance(board, player, piece_values))
        moves.append({'ply':ply, 'uci':uci, 'san':san, 'forcing':forcing, 'material_cp':balances[-1]})
    fates = [{'original_square':chess.square_name(original), 'current_square':chess.square_name(current) if current is not None else None,
        'fate':'captured' if current is None else 'still_on_original_square' if current == original else 'moved',
        'attacked_by_player':board.is_attacked_by(player,current) if current is not None else False}
        for original,current in target_locations.items()]
    tracked = {s for s in (*target_locations.values(),attacker,last_capture_destination) if s is not None}
    relevant = [board.san(m) for m in board.legal_moves if board.is_capture(m) and capture_square(board,m) in tracked]
    terminal = terminal_facts(board)
    return {'endpoint_fen':board.fen(), 'material_delta_cp':balances[-1]-initial,
        'captures_since_tactic_start':captures, 'original_target_fates':fates,
        'attacker_fate':'captured' if attacker is None else 'survives_at_endpoint',
        'attacker_square':chess.square_name(attacker) if attacker is not None else None,
        'attacker_attacked':board.is_attacked_by(not player,attacker) if attacker is not None else False,
        'legal_relevant_capture_or_recapture_options':relevant,
        'attacker_captured_original_target_cp':target_capture_cp,
        'other_net_material_cp':balances[-1]-initial-target_capture_cp,
        'causal_related_material_cp':None, 'causal_unrelated_material_cp':None,
        'causal_partition_note':'Geometric ledger only; no semantic attribution inferred.',
        'in_check':board.is_check(), 'recent_material_cp':balances[-4:],
        'material_stable_last_four_plies':len(balances)>=5 and len(set(balances[-4:]))==1,
        'endpoint_evaluation':endpoint_evaluation if not terminal.complete else None,
        'terminal':asdict(terminal), 'moves':moves}
