"""Portable actual-position scores. No engine, database, or UI side effects."""
from dataclasses import dataclass
from typing import Literal
import chess
from analysis_settings import Settings, setting, GeneratorSettings, BUILTIN_PROFILES
from candidate_lines import LineScore
from candidate_line_request import request_identity

@dataclass(frozen=True)
class EvaluationSettings(Settings):
    generator: GeneratorSettings = BUILTIN_PROFILES['quick'].generator
    display_limit_cp: int = setting(800, 'Visual clamp only; the numerical score remains unchanged.', minimum=100, maximum=5000, current=False)

@dataclass(frozen=True)
class GamePosition:
    game_id: int
    move_id: int | None
    step: int
    fen: str
    label: str

@dataclass(frozen=True)
class PositionEvaluation:
    """Canonical White POV; mate ownership survives distance zero; unknown is not zero."""
    position: GamePosition
    score: LineScore | None = None
    engine_identity: str = ''
    engine_name: str = ''
    engine_version: str = ''
    depth: int | None = None
    nodes: int | None = None
    provenance: str = 'missing_exact_evidence'
    complete: bool = False

    def __post_init__(self):
        if self.score is not None and self.score.score_pov != 'white':
            raise ValueError('Position evaluations require canonical White POV')
        if self.complete != (self.score is not None):
            raise ValueError('Complete evidence requires a score; unknown cannot have one')

    @property
    def evaluation_type(self) -> Literal['cp','mate','unknown']:
        return 'unknown' if self.score is None else 'mate' if self.score.mate_score is not None else 'cp'

    @property
    def side_to_move(self) -> str:
        return 'white' if chess.Board(self.position.fen).turn else 'black'

    def label(self, pov: str = 'white') -> str:
        """Format the shared canonical evaluation without inventing a numeric mate.

        Args:
            pov: White or Black score perspective.

        Returns:
            Signed pawn units, typed mate or an unknown marker.
        """
        return format_evaluation_score(self.score, pov)

    def advantage_label(self) -> str:
        """Canonical White number with the favored side, including mate ownership."""
        if self.score is None:
            return self.label()
        if self.score.mate_score is not None:
            side = self.score.mate_winner.title()
        elif self.score.score_cp == 0:
            side = "Equal"
        else:
            side = "White" if self.score.score_cp > 0 else "Black"
        return f"{self.label()} {side}"

    def white_fraction(self, limit_cp=800) -> float | None:
        """Bounded display strength, not material or win probability."""
        if self.score is None:
            return None
        if self.score.mate_score is not None:
            return 1.0 if self.score.mate_winner == 'white' else 0.0
        return (1 + max(-1, min(1, self.score.score_cp / limit_cp))) / 2


def actual_positions(game_id, moves) -> tuple[GamePosition, ...]:
    """Validate the entire stored actual sequence before exposing its position identities."""
    if not moves:
        return ()
    board = chess.Board(moves[0]['fen_before'])
    if not board.is_valid():
        raise ValueError('Invalid starting position')
    result = [GamePosition(game_id, None, 0, board.fen(), 'Start')]
    for index, row in enumerate(moves, 1):
        if board.fen() != row['fen_before']:
            raise ValueError('Actual-game FEN continuity mismatch')
        move = board.parse_uci(row['uci_played'])
        label = f"{board.fullmove_number}{'.' if board.turn else '…'} {board.san(move)}"
        board.push(move)
        if board.fen() != row['fen_after']:
            raise ValueError('Actual-game FEN after move mismatch')
        result.append(GamePosition(game_id, row['move_id'], index, board.fen(), label))
    return tuple(result)


def evaluation_from_lines(position, lines, settings=EvaluationSettings()):
    """Only complete, unrestricted evidence from this exact shared request is admissible."""
    config = settings.generator
    key = request_identity(config)
    fields = dict(engine_identity=key, engine_name=config.engine.engine_name, engine_version=config.engine.engine_version)
    if lines is None:
        return PositionEvaluation(position, **fields)
    if lines.fen != position.fen or lines.engine_identity != key or lines.generation_metadata.get('root_moves'):
        raise ValueError('Incompatible evaluation identity')
    if lines.generation_metadata.get('complete') is not True:
        return PositionEvaluation(position, provenance='incomplete_engine_evidence', **fields)
    if lines.generation_metadata.get('terminal'):
        board = chess.Board(position.fen)
        if not board.is_game_over():
            raise ValueError('Invalid terminal evidence')
        winner = ('black' if board.turn else 'white') if board.is_checkmate() else None
        score = LineScore(mate_score=0, mate_winner=winner) if winner else LineScore(score_cp=0)
        return PositionEvaluation(position, score, provenance='legal_terminal_position', complete=True, **fields)
    if not lines.lines:
        return PositionEvaluation(position, provenance='incomplete_engine_evidence', **fields)
    best = lines.lines[0]
    return PositionEvaluation(position, best.score.pov('white'), depth=best.depth, nodes=best.nodes,
                              provenance='engine_candidate_line_cache', complete=True, **fields)


def format_evaluation_score(score: LineScore | None, pov: str = 'white') -> str:
    """Format canonical scores consistently across game and advisory position views.

    Args:
        score: Typed cp/mate score, or None for unknown evidence.
        pov: White or Black display perspective.

    Returns:
        Signed pawn units, M-distance with ownership, or an unknown marker.

    Raises:
        ValueError: The requested perspective is invalid.
    """
    if score is None:
        return '—'
    value = score.pov(pov)
    if value.mate_score is not None:
        return ('' if value.mate_winner == pov else '-') + f'M{abs(value.mate_score)}'
    return f'{value.score_cp / 100:+.2f}'
