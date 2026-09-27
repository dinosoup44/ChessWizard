"""Pure legal replay producing opening knowledge, never move-quality judgments."""
import chess
from collections.abc import Iterable, Sequence, Mapping
from typing import Any
from opening_intelligence_lookup import OpeningBookLookup
from opening_book_models import standard_board
from opening_intelligence_models import (VariationContext, BookPositionVisit, OpeningMoveAssessment,
                                         OpeningGameAssessment, identity)


def assess_game(lookup: OpeningBookLookup, moves_uci: Iterable[str], *,
                initial_fen: str = chess.STARTING_FEN, game_id: int | None = None,
                user_color: str | None = None, stored_moves: Sequence[Mapping[str, Any]] | None = None,
                game_namespace: str = 'in_memory') -> OpeningGameAssessment:
    """Replay opening facts, gating opted-in books by actual defining positions.

    Args:
        lookup: Indexed authored graph and optional entry contract.
        moves_uci: Actual legal game moves, never proposed analysis.
        initial_fen: Legal starting position for the game.
        game_id: Optional persistent game identity.
        user_color: Known player side or None.
        stored_moves: Optional rows whose exact FEN continuity must match replay.
        game_namespace: Namespace preventing cross-database game-ID collisions.

    Returns:
        Immutable membership, entry, variation and deviation facts. Setup moves
        before an explicit entry cannot create gaps or deviations.

    Raises:
        ValueError: Moves, user color or stored continuity are inconsistent.
    """
    if user_color not in (None,'white','black'):raise ValueError('Unknown user color must remain explicit.')
    ucis=tuple(moves_uci)
    if stored_moves is not None and len(stored_moves)!=len(ucis):raise ValueError('Stored move count mismatch.')
    board=standard_board(initial_fen)
    position=lookup.lookup(board)
    contract=lookup.entry_contract
    active=contract is None or (position.found and position.identity.canonical_fen in contract.positions)
    entry_ply=0 if contract and active else None
    context=(VariationContext(((),),True) if position.position_id==lookup.snapshot.book.root_position_id else position.variation_context)
    initial_context=context;final_context=context;last_supported=context
    rows,visits,followed=[],[],[]
    if position.found and active:visits.append(BookPositionVisit(0,position.position_id,position.identity,'Start'))
    ever_known=position.found and active;first=None;last_before=None;run=maximum=0
    for ply,uci in enumerate(ucis,1):
        stored=stored_moves[ply-1] if stored_moves is not None else None
        if stored is not None and board.fen()!=stored['fen_before']:raise ValueError(f'Stored FEN discontinuity at ply {ply}.')
        move=board.parse_uci(uci)
        if not move or move not in board.legal_moves:raise ValueError(f'Illegal actual move at ply {ply}.')
        actor='white' if board.turn else 'black'
        san=board.san(move);number=board.fullmove_number;label=f"{number}{'.' if board.turn else '…'} {san}"
        edge=next((m for m in position.available_moves if m.move_uci==move.uci()),None)
        deviation=active and position.found and edge is None
        is_first=deviation and first is None
        if is_first:first=ply;last_before=visits[-1]
        relation=None if not deviation or user_color is None else 'user' if actor==user_color else 'opponent'
        state='in_book' if edge else 'move_not_authored' if position.available_moves else 'continuation_not_authored' if position.found else 'position_not_in_book'
        board.push(move)
        if stored is not None and board.fen()!=stored['fen_after']:raise ValueError(f'Stored resulting FEN mismatch at ply {ply}.')
        after=lookup.lookup(board)
        was_active=active
        if contract and not active and after.found and after.identity.canonical_fen in contract.positions:
            active=True
            entry_ply=ply
        entry=active and after.found and (not was_active or not position.found)
        reentry=entry and ever_known
        if edge:
            after_context=lookup.advance_context(context,edge)
            run+=1;maximum=max(maximum,run)
            if edge.variation_name and after_context.path and after_context.path not in followed:
                followed.append(after_context.path)
        else:
            after_context=after.variation_context
            # Re-entry may be ambiguous in the graph yet compatible with a named
            # prefix actually observed earlier. Preserve that evidence when present.
            if after.found and last_supported.observed and last_supported.path:
                prefix=last_supported.path
                compatible=tuple(p for p in after_context.paths if p[:len(prefix)]==prefix)
                if compatible:
                    after_context=VariationContext(compatible,False,after_context.complete)
            run=0
        if after.found and active:
            visits.append(BookPositionVisit(ply,after.position_id,after.identity,label))
            final_context=after_context
            if after_context.path and after_context.observed:last_supported=after_context
            ever_known=True
        rows.append(OpeningMoveAssessment(game_id,stored['move_id'] if stored is not None else None,ply,number,
            actor,move.uci(),san,label,position.identity,position.position_id if was_active else None,
            after.identity,after.position_id if active else None,
            edge is not None and active,edge.weight if edge and active else None,
            position.available_moves if was_active else (),position.preferred_move if was_active else None,
            context if was_active else VariationContext(),after_context if active else VariationContext(),
            state if was_active else 'position_not_in_book',deviation,is_first,relation,reentry,entry,lookup.provenance))
        position,context=after,after_context
    in_book=sum(row.played_move_in_book for row in rows)
    return OpeningGameAssessment(game_id,identity((game_namespace,game_id,initial_fen,ucis,user_color,
        tuple(row['move_id'] for row in stored_moves) if stored_moves is not None else None)),lookup.provenance,user_color,
        tuple(rows),tuple(visits),initial_context,final_context,tuple(followed),in_book,len(rows)-in_book,
        sum(bool(row.available_moves) for row in rows),
        None if user_color is None else sum(row.played_move_in_book and row.actor_color==user_color for row in rows),
        None if user_color is None else sum(row.played_move_in_book and row.actor_color!=user_color for row in rows),
        first,last_before,visits[-1] if visits else None,sum(row.reentry for row in rows),maximum,
        active if contract else maximum>=lookup.policy.min_consecutive_plies, entry_ply=entry_ply)
