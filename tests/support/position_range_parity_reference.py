"""Independent python-chess replay for audit tie-breaks; no toolkit or analyzer imports."""
import chess


def replay_reference(fen: str, moves: list[str], values: dict[int, int]) -> dict:
    """Replay a legal supplied line independently of the shared toolkit.

    Args:
        fen: Initial board in FEN notation.
        moves: Legal UCI continuation to replay.
        values: Supplied result population.

    Returns:
        Structured comparison or factual result for the supplied inputs.

    Raises:
        ValueError: Supplied files, positions or evidence fail the validation contract.
    """
    board = chess.Board(fen)
    player = board.turn
    original = board.piece_map()
    location = {square: square for square in original}
    fates = {square: dict(current_square=square, piece_type=piece.piece_type, color=piece.color,
                         capture_ply=None, captured_by=None, move_count=0, promoted=False)
             for square, piece in original.items()}
    captures, promotions, steps = [], [], []
    def totals():
        return tuple(sum(values[p.piece_type] for p in board.piece_map().values() if p.color == color)
                     for color in (True, False))
    timeline = [totals()]
    first_id, first_destination = None, None
    for ply, uci in enumerate(moves, 1):
        move = chess.Move.from_uci(uci)
        if not board.is_legal(move) or not move:
            raise ValueError(f"Independent replay: illegal move at ply {ply}: {uci}")
        actor = location[move.from_square]
        side, before, san = board.turn, board.fen(), board.san(move)
        old_type = board.piece_type_at(move.from_square)
        castle, ep = board.is_castling(move), board.is_en_passant(move)
        enemy_before = {s for s, p in board.piece_map().items() if p.color != side}
        rooks_before = set(board.pieces(chess.ROOK, side))
        board.push(move)
        enemy_after = {s for s, p in board.piece_map().items() if p.color != side}
        victims = enemy_before - enemy_after
        if len(victims) > 1:
            raise ValueError("A legal move removed more than one enemy identity")
        destination = board.king(side) if castle else move.to_square
        if victims:
            square = victims.pop(); victim = location.pop(square); fate = fates[victim]
            captures.append(dict(ply=ply, square=square, destination=destination, victim=victim,
                capturer=actor, victim_type=fate['piece_type'], victim_color=fate['color'],
                value=values[fate['piece_type']], en_passant=ep))
            fate.update(current_square=None, capture_ply=ply, captured_by=actor)
        del location[move.from_square]
        if castle:
            rook_sources = rooks_before - set(board.pieces(chess.ROOK, side))
            rook_destinations = set(board.pieces(chess.ROOK, side)) - rooks_before
            if rook_sources:
                source, target = rook_sources.pop(), rook_destinations.pop()
                rook_id = location.pop(source); location[target] = rook_id
                fates[rook_id]['current_square'] = target; fates[rook_id]['move_count'] += 1
        location[destination] = actor
        fates[actor]['current_square'] = destination
        fates[actor]['piece_type'] = board.piece_type_at(destination)
        fates[actor]['move_count'] += 1
        if move.promotion:
            fates[actor]['promoted'] = True
            promotions.append(dict(ply=ply, piece=actor, to_type=move.promotion,
                                   delta=values[move.promotion]-values[old_type]))
        if ply == 1:
            first_id, first_destination = actor, destination
        timeline.append(totals())
        steps.append(dict(ply=ply, uci=uci, san=san, before_fen=before, after_fen=board.fen(),
                          in_check=board.is_check()))
    legal = []
    for move in board.legal_moves:
        if not board.is_capture(move):
            continue
        copy = board.copy(stack=False); copy.push(move)
        removed = {s for s,p in board.piece_map().items() if p.color != board.turn} - {
                    s for s,p in copy.piece_map().items() if p.color != board.turn}
        square = removed.pop(); victim = location[square]
        legal.append(dict(uci=move.uci(), san=board.san(move), square=square,
                          destination=move.to_square, victim=victim, capturer=location[move.from_square],
                          value=values[board.piece_type_at(square)], side=board.turn))
    for identity, fate in fates.items():
        square = fate['current_square']
        fate['attackers'] = sorted(board.attackers(not fate['color'], square)) if square is not None else []
        fate['defenders'] = sorted(board.attackers(fate['color'], square)) if square is not None else []
    outcome = board.outcome(claim_draw=False)
    terminal = ('checkmate' if board.is_checkmate() else 'stalemate' if board.is_stalemate() else
                'insufficient_material' if board.is_insufficient_material() else 'other_draw' if outcome else 'not_terminal')
    return dict(fen=board.fen(), player=player, captures=captures, promotions=promotions,
        fates=fates, timeline=timeline, steps=steps, legal_captures=legal,
        attacker=first_id, tactic_destination=first_destination, in_check=board.is_check(),
        terminal=terminal, terminal_result=outcome.result() if outcome else None,
        fifty_claimable=board.can_claim_fifty_moves(), repetition_claimable=board.can_claim_threefold_repetition())
