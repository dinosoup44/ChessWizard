"""Generic immutable read models for review, dashboards and future training links."""
from dataclasses import dataclass
from tactic_query import TacticQuery
from feedback import FeedbackContextBuilder, FeedbackGenerator, FeedbackResult
from stored_line import StoredLine
from exchange_presentation_repository import StoredExchangeReader
from tactic_board_annotations import tactical_target_squares


@dataclass(frozen=True)
class TacticalMoment:
    candidate_id: int
    move_id: int
    game_id: int
    ply_number: int
    move_number: int
    color: str
    fen_before: str
    tactic_type: str
    title: str
    played_move: str
    suggested_move: str
    solution_uci: str | None
    proof_line: str
    explanation: str
    motifs: tuple[str, ...]
    context_motifs: tuple[str, ...]
    presentation_level: str
    has_opportunity: bool
    feedback: FeedbackResult
    stored_line: StoredLine
    target_squares: tuple[int, ...] = ()

    @property
    def list_label(self):
        note = "Note: " if self.presentation_level=="positional_note" else ""
        motifs = " · " + ", ".join(self.motifs) if self.motifs else ""
        return f"{self.move_number} {self.color.capitalize()} · {note}{self.title}{motifs}"


def present_candidate(row, opportunity=None):
    context = FeedbackContextBuilder().build(row, opportunity)
    result = FeedbackGenerator().generate(context)
    return TacticalMoment(row["candidate_id"], row["move_id"], row["game_id"], row["ply_number"],
        row["move_number"], row["color"], row["fen_before"], row["tactic_type"], result.title,
        context.played_move or "Not recorded", context.recommended_move or "Not recorded",
        row.get("solution_move_uci"), context.proof_line or "", result.explanation,
        result.motif_labels, result.context_motif_labels, result.presentation_level,
        context.primary_outcome is not None, result,
        StoredLine.from_san(context.fen_before, result.proof_line, context.candidate_id),
        tactical_target_squares(context))


class TacticReadService:
    def __init__(self, connection):
        self.connection = connection
        self.query = TacticQuery(connection)
        self.exchange_reader = StoredExchangeReader(connection)

    def moments_for_game(self, game_id):
        return [present_candidate(self.exchange_reader.enrich(row)) for row in self.query.candidates(game_id=game_id)]

    def moment_for_candidate(self, game_id, candidate_id):
        rows = self.query.candidates(game_id=game_id, candidate_id=candidate_id)
        return present_candidate(self.exchange_reader.enrich(rows[0])) if rows else None


def decision_step(moves, moment):
    """Resolve canonical move identity to the existing replay step, not ply-1."""
    for index,row in enumerate(moves):
        if row["move_id"]==moment.move_id:
            if row["fen_before"] != moment.fen_before:
                raise ValueError("Tactic decision position disagrees with stored move")
            return index
    raise ValueError("Tactic does not belong to the loaded game's moves")
