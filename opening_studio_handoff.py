"""Portable exact-position Review-to-Studio handoff; staging never writes a book."""
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
import chess
from opening_book_line import BookLinePlan, plan_book_line
from opening_book_models import BookSnapshot, PositionIdentity, position_identity
from opening_engine_models import OpeningEngineAnchor, saved_opening_anchor
from opening_exploration import OpeningExplorationState
from opening_intelligence_lookup import OpeningBookLookup, advance_context
from opening_intelligence_models import OpeningGameAssessment, VariationContext


@dataclass(frozen=True)
class OpeningStudioHandoff:
    """Carry source context and an optional uncommitted played continuation.

    Args:
        anchor: Exact saved route to the requested or nearest known position.
        requested_position: Canonical position the owner requested.
        source_game_id: Actual game identifier, never a new game/window selection.
        source_ply: Number of actual plies reaching the requested position.
        game_identity: Immutable legally assessed source game identity.
        variation: Relevant observed/inferred variation context, including ambiguity.
        candidate_moves: Actual moves from the nearest known anchor, still uncommitted.
    """
    anchor: OpeningEngineAnchor
    requested_position: PositionIdentity
    source_game_id: int
    source_ply: int
    game_identity: str
    variation: VariationContext
    candidate_moves: tuple[str, ...] = ()



def studio_source_step(lookup: OpeningBookLookup, assessment: OpeningGameAssessment,
                       moves: Sequence[Mapping], game_id: int, actual_step: int,
                       displayed_fen: str, *, exploration: OpeningExplorationState | None = None) -> int:
    """Validate a displayed cursor against loaded game facts without I/O or graph traversal.

    Args:
        lookup: Currently selected immutable opening.
        assessment: Facts for the displayed game, independent of a browsed moment.
        moves: Actual loaded move records, including before/after FENs.
        game_id: Identifier of the game currently displayed.
        actual_step: Number of actual plies reached by the game cursor.
        displayed_fen: Board currently visible to the user.
        exploration: Optional explicit authored-line state, never a tactic proof.

    Returns:
        Actual route endpoint for handoff. Authored exploration uses its own
        decision anchor while preserving the separate Return to Game cursor.

    Raises:
        ValueError: The opening, game facts, cursor, or displayed board is stale.
    """
    if lookup.provenance != assessment.provenance or game_id != assessment.game_id:
        raise ValueError('Wait for the selected Opening and current game to finish loading.')
    if not moves or len(moves) != assessment.total_plies or not 0 <= actual_step <= len(moves):
        raise ValueError('Select a valid position in the loaded game.')
    if tuple((m['move_id'], m['uci_played']) for m in moves) != tuple(
            (m.move_id, m.played_uci) for m in assessment.moves):
        raise ValueError('The actual game changed. Reload it first.')
    step = actual_step
    if exploration is not None:
        if (not exploration.is_current(assessment) or not 1 <= exploration.anchor_ply <= len(moves)
                or not 0 <= exploration.ply <= len(exploration.line)):
            raise ValueError('Return to Game before opening this position in Studio.')
        step = exploration.anchor_ply - 1
    actual_fen = moves[step]['fen_before'] if step < len(moves) else moves[-1]['fen_after']
    actual_position = assessment.moves[step].position if step < len(moves) else assessment.moves[-1].after_position
    if position_identity(actual_fen) != actual_position:
        raise ValueError('The displayed game position no longer matches its opening facts.')
    if exploration is not None and chess.Board(exploration.decision_fen).fen() != chess.Board(actual_fen).fen():
        raise ValueError('The authored line no longer matches its actual game anchor.')
    expected_fen = exploration.fen if exploration is not None else actual_fen
    if chess.Board(displayed_fen).fen() != chess.Board(expected_fen).fen():
        raise ValueError('Return to the current game position before opening Studio.')
    return step


def _saved_path(lookup: OpeningBookLookup, target: int, context: VariationContext) -> tuple[int, ...]:
    """Prefer the unambiguous named route while bounding cyclic graph traversal."""
    required=tuple(v.move_id for v in context.path)
    queue=deque([(lookup.snapshot.book.root_position_id,(),0)])
    seen=set();fallback=None
    while queue:
        position,path,matched=queue.popleft()
        key=(position,matched)
        if key in seen:continue
        seen.add(key)
        if position==target:
            if matched==len(required):return path
            if fallback is None:fallback=path
        for edge in lookup.outgoing.get(position,()):
            advance=matched+int(matched<len(required) and edge.move_id==required[matched])
            queue.append((edge.to_position_id,(*path,edge.move_id),advance))
    if fallback is not None:return fallback
    raise ValueError('The requested position is not reachable through active book moves.')


def make_studio_handoff(lookup: OpeningBookLookup, assessment: OpeningGameAssessment,
                        moves: Sequence[Mapping], actual_step: int, *,
                        explored_fen: str | None = None, explored_moves: tuple[int, ...] | None = None) -> OpeningStudioHandoff:
    """Stage exactly the missing played path to one requested position.

    Args:
        lookup: Selected immutable book with managed provenance.
        assessment: Matching legal replay of the loaded game.
        moves: Loaded actual move records, including original before/after FENs.
        actual_step: Actual position after this many plies (zero means game start).
        explored_fen: Optional currently explored authored position; it must be known.
        explored_moves: Exact authored route from the actual anchor; preserves named transpositions.

    Returns:
        Exact saved handoff or nearest-known anchor plus explicit candidate plies.

    Raises:
        ValueError: Source/book identity changed, selection is invalid or no known anchor exists.
    """
    if lookup.provenance!=assessment.provenance or not assessment.game_id:
        raise ValueError('Refresh the selected book/game before opening Studio.')
    if not 0<=actual_step<=len(moves) or not moves or len(moves)!=assessment.total_plies:
        raise ValueError('Select an actual game position.')
    if tuple((m['move_id'],m['uci_played']) for m in moves)!=tuple((m.move_id,m.played_uci) for m in assessment.moves):
        raise ValueError('The actual game changed. Reload it first.')
    nearest=None;route=None;previous=None
    for step in range(actual_step+1):
        fen=moves[step-1]['fen_after'] if step else moves[0]['fen_before']
        context=assessment.moves[step-1].variation_after if step else assessment.initial_variation
        found=lookup.lookup(fen)
        if found.found:
            edge=next((e for e in lookup.outgoing.get(previous,()) if step and e.move_uci==moves[step-1]['uci_played']),None)
            route=(*route,edge.move_id) if route is not None and edge and edge.to_position_id==found.position_id else _saved_path(lookup,found.position_id,context)
            nearest=(step,route,found.position_id)
        else:route=None
        previous=found.position_id
    requested=position_identity(fen)
    if explored_fen is not None:
        found=lookup.lookup(explored_fen)
        if not found.found:raise ValueError('The explored book position is no longer available.')
        if explored_moves is not None:
            if nearest is None or nearest[0]!=actual_step:
                raise ValueError('An explored route must start at the actual known book anchor.')
            route=(*nearest[1],*explored_moves)
            destination=saved_opening_anchor(lookup.snapshot,lookup.provenance.library_identity,route)
            if destination.position!=found.identity:
                raise ValueError('The explored route does not reach the selected position.')
            edges={edge.move_id:edge for edge in lookup.snapshot.moves}
            for move_id in explored_moves:context=advance_context(context,edges[move_id])
        else:
            context=found.variation_context
            route=_saved_path(lookup,found.position_id,context)
        nearest=(actual_step,route,found.position_id)
        requested=found.identity
    if nearest is None:raise ValueError('This game has no known book position before the requested point.')
    step,path,_=nearest
    anchor=saved_opening_anchor(lookup.snapshot,lookup.provenance.library_identity,path)
    candidate=tuple(m['uci_played'] for m in moves[step:actual_step]) if explored_fen is None else ()
    board=chess.Board(anchor.fen)
    for uci in candidate:board.push(board.parse_uci(uci))
    if position_identity(board)!=requested:raise ValueError('Played continuation does not reach the requested position.')
    return OpeningStudioHandoff(anchor,requested,assessment.game_id,actual_step,assessment.game_identity,context,candidate)


def handoff_line_plan(snapshot: BookSnapshot, library_id: str, handoff: OpeningStudioHandoff,
                      *, variation_name: str = '') -> BookLinePlan:
    """Validate an explicitly confirmed staged path against the still-current book.

    Args:
        snapshot: Current destination snapshot.
        library_id: Resolved canonical managed namespace.
        handoff: Review source and saved insertion anchor.
        variation_name: Optional user name for the first new edge.

    Returns:
        Shared atomic insert-only merge plan; callers explicitly commit through the repository.

    Raises:
        ValueError: Revision, route or selected book differs, or there is no staged path.
    """
    if saved_opening_anchor(snapshot,library_id,handoff.anchor.path)!=handoff.anchor:
        raise ValueError('The book changed after this handoff. Return to Review and refresh.')
    return plan_book_line(snapshot,handoff.anchor.position_id,handoff.anchor.fen,handoff.candidate_moves,
                          variation_name=variation_name)


def handoff_disposition(snapshot: BookSnapshot, library_id: str,
                        handoff: OpeningStudioHandoff) -> Literal["pending", "satisfied", "superseded"]:
    """Inspect a proposal without granting permission to commit a stale plan.

    Args:
        snapshot: Current authored graph, including any normal manual saves.
        library_id: Actual selected managed library namespace.
        handoff: Original proposal and its exact saved anchor.

    Returns:
        Satisfied when the full active route exists; superseded when authoring or
        destination changes invalidate the proposal; otherwise pending.
    """
    if library_id != handoff.anchor.library_identity or snapshot.book.book_id != handoff.anchor.book_id:
        return "superseded"
    try:
        anchor = saved_opening_anchor(snapshot, library_id, handoff.anchor.path)
        edges = {edge.move_id: edge for edge in snapshot.moves}
        if (anchor.position != handoff.anchor.position or anchor.fen != handoff.anchor.fen
                or any(not edges[mid].active for mid in anchor.path)):
            return "superseded"
        plan = plan_book_line(snapshot, anchor.position_id, anchor.fen, handoff.candidate_moves)
    except ValueError:
        return "superseded"
    if plan.steps[-1].target != handoff.requested_position:
        return "superseded"
    if plan.new_edges == 0:
        return "satisfied"
    # Normal authoring owns its saves. Never rebase old write consent onto new contents.
    return "pending" if anchor == handoff.anchor else "superseded"
