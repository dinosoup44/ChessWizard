"""Targeted attack and legal capture facts for the actual side to move."""
from collections.abc import Mapping, Iterable
import chess
from board_analysis import attackers, capture_square, legal_mobility, piece_safety
from .models import AttackState, LegalCapture, PieceIdentity, RelevantRecapture


def legal_captures(board: chess.Board, identities: Mapping[int, PieceIdentity],
                   values: Mapping[int, int]) -> tuple[LegalCapture, ...]:
    """Generate king-safe captures once per queried position, including the EP victim square."""
    result = []
    for uci in legal_mobility(board).captures_uci:
        move = chess.Move.from_uci(uci)
        square = capture_square(board, move)
        victim = board.piece_at(square)
        result.append(LegalCapture(board.turn, uci, board.san(move), identities[move.from_square],
            identities[square], victim.piece_type, square, move.to_square, values[victim.piece_type],
            board.is_en_passant(move)))
    return tuple(result)


def attack_state(board: chess.Board, square: int, identities: Mapping[int, PieceIdentity],
                 captures: tuple[LegalCapture, ...]) -> AttackState:
    safety = piece_safety(board, square)
    white, black = attackers(board, square, True), attackers(board, square, False)
    piece = identities.get(square)
    against = tuple(c for c in captures if c.victim == piece) if piece else ()
    by = tuple(c for c in captures if c.capturer == piece) if piece else ()
    reason = "empty_square" if safety is None else "king_is_not_capturable" if (
        safety.piece.piece_type == chess.KING) else "opponent_not_to_move" if (
        safety.piece.color == board.turn) else "evaluated_for_actual_side_to_move"
    legal_sources = tuple(sorted({chess.Move.from_uci(c.uci).from_square for c in against}))
    return AttackState(square, piece, safety.attackers if safety else (), safety.defenders if safety else (),
        legal_sources if reason in ("evaluated_for_actual_side_to_move", "king_is_not_capturable") else None,
        reason, tuple(s for s in sorted(set(white + black)) if board.is_pinned(board.color_at(s), s)),
        white, black, tuple(sorted({c.victim_square for c in by})), against, by, board.is_check())


def relevant_recaptures(captures: tuple[LegalCapture, ...], *, attacker: PieceIdentity | None = None,
        targets: Iterable[PieceIdentity] = (), recent_capture_squares: Iterable[int] = (),
        exchange_participants: Iterable[PieceIdentity] = ()) -> tuple[RelevantRecapture, ...]:
    """Relations select possibilities; they make no claim about best play or causal payoff."""
    targets, recent, participants = set(targets), set(recent_capture_squares), set(exchange_participants)
    result = []
    for capture in captures:
        relations = []
        if capture.victim == attacker:
            relations.append("captures_attacker")
        if capture.victim in targets:
            relations.append("captures_target")
        if capture.destination in recent or capture.victim_square in recent:
            relations.append("onto_recent_capture_square")
        if capture.capturer == attacker:
            relations.append("by_attacker")
        if capture.capturer in participants:
            relations.append("by_exchange_participant")
        if relations:
            result.append(RelevantRecapture(capture, tuple(relations)))
    return tuple(result)
