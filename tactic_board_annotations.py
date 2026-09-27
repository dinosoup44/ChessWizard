"""Read explicit stored participants for display; never infer tactical geometry."""
import json
import chess


def tactical_target_squares(context) -> tuple[int, ...]:
    """Return recorded enemy targets still present at the decision position."""
    squares = []
    for relation in context.relationships:
        squares.append(relation.rear_target.square)
        if relation.intervening_piece:
            squares.append(relation.intervening_piece.square)
    raw = context.opportunity_metadata_json if context.opportunity_metadata_json is not None else context.legacy_metadata_json
    try:
        metadata = json.loads(raw or "{}")
        for key in ("geometric_targets", "targets"):
            values = metadata.get(key, ()) if isinstance(metadata, dict) else ()
            if isinstance(values, (list, tuple)):
                squares.extend(item.get("square") for item in values if isinstance(item, dict))
        board = chess.Board(context.fen_before)
    except (ValueError, TypeError):
        return ()
    targets = set()
    for value in squares:
        try:
            square = chess.parse_square(value) if isinstance(value, str) else value
            if type(square) is int and square in chess.SQUARES:
                piece = board.piece_at(square)
                if piece and piece.color != board.turn:
                    targets.add(square)
        except ValueError:
            pass
    return tuple(sorted(targets))


def stationary_target_squares(targets: tuple[int, ...], positions: tuple[str, ...]) -> tuple[int, ...]:
    """Keep recorded squares only while their original participants stay there.

    Inspect the whole displayed prefix: a piece moving away and back does not
    revive its decision-position annotation. No new tactical targets are inferred.
    """
    if not positions:
        return ()
    initial = chess.Board(positions[0])
    remaining = {square for square in targets if initial.piece_at(square) is not None}
    for fen in positions[1:]:
        board = chess.Board(fen)
        remaining = {square for square in remaining
                     if board.piece_at(square) == initial.piece_at(square)}
    return tuple(sorted(remaining))
