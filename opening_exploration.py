"""Portable authored-line exploration with an immutable actual-game anchor."""
from dataclasses import dataclass, replace
import chess
from opening_intelligence_lookup import advance_context
from opening_intelligence_models import BookProvenance, VariationContext


@dataclass(frozen=True)
class OpeningLineStep:
    move_id: int
    uci: str
    san: str
    label: str
    fen_after: str
    variation: VariationContext


@dataclass(frozen=True)
class OpeningExplorationState:
    game_id: int | None
    game_identity: str
    provenance: BookProvenance
    anchor_ply: int
    decision_fen: str
    variation_before: VariationContext
    line: tuple[OpeningLineStep, ...]
    ply: int = 1
    user_suggestion_uci: str | None = None

    @property
    def fen(self):
        return self.line[self.ply-1].fen_after if self.ply else self.decision_fen

    @property
    def variation(self):
        return self.line[self.ply-1].variation if self.ply else self.variation_before

    @property
    def last_move(self):
        return chess.Move.from_uci(self.line[self.ply-1].uci) if self.ply else None

    @property
    def suggestion(self):
        # The root recommendation must not remain painted over later positions.
        return self.user_suggestion_uci if self.ply <= 1 else None

    def step(self, offset):
        return replace(self, ply=max(0, min(len(self.line), self.ply + offset)))

    def is_current(self, assessment):
        return (assessment is not None and self.game_id == assessment.game_id
                and self.game_identity == assessment.game_identity and self.provenance == assessment.provenance)


def relevant_actual_moves(assessment):
    """Keep known regions, intervening gaps and the departure just beyond coverage."""
    if assessment is None or not assessment.meaningful_match:
        return ()
    last = assessment.last_known_position.after_ply if assessment.last_known_position else 0
    return assessment.moves[:min(assessment.total_plies, last + 1)]


def explore_book_move(lookup, assessment, anchor_ply, decision_fen, move_id):
    """Freeze one selected continuation; stop at an unchosen fork, leaf or cycle.

    Follow authored Preferred edges, otherwise a sole active continuation. This is
    book navigation, not an evaluation or a choice of an engine-best line.
    """
    if lookup.provenance != assessment.provenance:
        raise ValueError('Book changed; refresh opening facts before exploring.')
    if not 1 <= anchor_ply <= assessment.total_plies:
        raise ValueError('An actual-game move is required as the exploration anchor.')
    actual = assessment.moves[anchor_ply-1]
    board = chess.Board(decision_fen)
    position = lookup.lookup(board)
    if position.identity != actual.position:
        raise ValueError('Book decision position does not match the actual anchor.')
    selected = next((move for move in position.available_moves if move.move_id == move_id), None)
    if selected is None:
        raise ValueError('Choose an active book move from this decision position.')
    suggestion = (selected.move_uci if actual.deviation_relation == 'user'
                  and actual.deviation and actual.preferred_move == selected else None)
    context = actual.variation_before
    visited = {position.identity}
    line = []
    edge = selected
    while edge is not None:
        move = board.parse_uci(edge.move_uci)
        label = f'{board.fullmove_number}{"." if board.turn else "…"} {board.san(move)}'
        board.push(move)
        context = advance_context(context, edge)
        line.append(OpeningLineStep(edge.move_id, move.uci(), edge.san, label, board.fen(), context))
        reached = lookup.lookup(board)
        if reached.identity in visited:
            break
        visited.add(reached.identity)
        choices = reached.available_moves
        edge = reached.preferred_move or (choices[0] if len(choices) == 1 else None)
    return OpeningExplorationState(assessment.game_id, assessment.game_identity, assessment.provenance, anchor_ply,
                                   decision_fen, actual.variation_before, tuple(line), 1, suggestion)
