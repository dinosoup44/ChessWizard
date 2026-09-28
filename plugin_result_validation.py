"""Validate plugin facts independently with the core's chess board representation."""
import chess
from chesswizard_plugin_api import MaterialFacts, PositionContext


def validate_material_facts(context: PositionContext, result: MaterialFacts) -> None:
    """Reject incorrect, duplicate, stale, or unsupported factual responses.

    Args:
        context: Original context held by the parent process.
        result: Typed response reconstructed from bounded JSON.

    Raises:
        ValueError: Evidence disagrees with the board or request identity.
    """
    board = chess.Board(context.fen)
    if not board.is_valid():
        raise ValueError("Invalid standard-chess position")
    if result.request_id != context.request_id or result.fen != context.fen:
        raise ValueError("Response context does not match the request")
    expected_squares = {
        (chess.square_name(square), "white" if piece.color else "black", chess.piece_name(piece.piece_type))
        for square, piece in board.piece_map().items()
    }
    actual_squares = {(fact.square, fact.color, fact.piece) for fact in result.squares}
    if len(actual_squares) != len(result.squares) or actual_squares != expected_squares:
        raise ValueError("Square evidence is incorrect or duplicated")
    expected_counts = {
        ("white" if color else "black", chess.piece_name(piece), len(board.pieces(piece, color)))
        for color in chess.COLORS for piece in chess.PIECE_TYPES
    }
    actual_counts = {(fact.color, fact.piece, fact.count) for fact in result.counts}
    if any(type(fact.count) is not int for fact in result.counts):
        raise ValueError("Counts must be integers, not booleans or floating point")
    if len(actual_counts) != len(result.counts) or actual_counts != expected_counts:
        raise ValueError("Material counts are incorrect or duplicated")