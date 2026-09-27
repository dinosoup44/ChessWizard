"""Pure move-quality assessment from compatible root-conditioned engine evidence."""
from dataclasses import dataclass
from statistics import mean, median
import chess
from candidate_lines import LineScore
from candidate_line_request import request_identity
from board_analysis.phase import GamePhase, game_phase
from move_quality_settings import MoveQualitySettings
from position_evaluation import actual_positions


@dataclass(frozen=True)
class QualityMove:
    game_id: int
    move_id: int
    step: int
    fen: str
    mover_color: str
    played_move: str
    played_san: str

    def __post_init__(self):
        board = chess.Board(self.fen)
        if not board.is_valid() or self.mover_color != ('white' if board.turn else 'black'):
            raise ValueError('Mover color must match a valid decision FEN')
        board.parse_uci(self.played_move)


def quality_moves(game_id, moves):
    """Validate full actual-game continuity before reading or generating move evidence."""
    positions = actual_positions(game_id, moves)
    return tuple(QualityMove(game_id, row['move_id'], step, positions[step-1].fen,
                            'white' if chess.Board(positions[step-1].fen).turn else 'black',
                            row['uci_played'], chess.Board(positions[step-1].fen).san(chess.Move.from_uci(row['uci_played'])))
                 for step, row in enumerate(moves, 1))


@dataclass(frozen=True)
class MoveLoss:
    state: str
    eval_loss_cp: int | None = None
    accuracy: float | None = None
    raw_difference_cp: int | None = None


def cp_accuracy(loss, settings=MoveQualitySettings()):
    """ChessWizard's own smooth loss transform; unknown is never a perfect move."""
    if loss is None:
        return None
    if type(loss) is not int or loss < 0:
        raise ValueError('A loss must be a nonnegative integer centipawn value')
    return 100.0 / (1.0 + (loss / settings.half_accuracy_loss_cp) ** 2)


def mover_loss(best, played, color, settings=MoveQualitySettings()):
    """Compare from the mover's POV, keeping mate states out of centipawn arithmetic.

    A restricted line beating the purported unrestricted best is contradictory
    evidence, not a bonus or an invented zero loss. It stays unscored.
    """
    if color not in {'white', 'black'}:
        raise ValueError('Explicit mover color required')
    if best is None or played is None:
        return MoveLoss('missing_evidence')
    a, b = best.pov(color), played.pov(color)
    if a.score_cp is not None and b.score_cp is not None:
        loss = a.score_cp - b.score_cp
        if loss < 0:
            return MoveLoss('inconsistent_estimates', raw_difference_cp=loss)
        return MoveLoss('centipawn', loss, cp_accuracy(loss, settings), loss)
    own_a = a.mate_winner == color if a.mate_score is not None else None
    own_b = b.mate_winner == color if b.mate_score is not None else None
    if a.mate_score is not None and b.mate_score is not None and own_a == own_b:
        delay = max(0, abs(b.mate_score) - abs(a.mate_score)) if own_a else max(0, abs(a.mate_score) - abs(b.mate_score))
        penalty = min(settings.mate_distance_max_penalty, settings.mate_distance_penalty * delay)
        return MoveLoss('mate_preserved' if own_a else 'forced_mate_retained', accuracy=100.0-penalty)
    if own_b is False:
        return MoveLoss('walked_into_mate', accuracy=0.0)
    if own_a is True and b.score_cp is not None:
        return MoveLoss('lost_forced_mate', accuracy=settings.lost_mate_accuracy)
    # Escaping an allegedly forced mate, or finding a mate missed by the root
    # search, exposes inconsistent search horizons. Keep the transition explicit.
    return MoveLoss('mate_escaped_unresolved' if own_a is False else 'mate_found_unresolved')


def compatible_lines(lines, fen, settings, root_moves=()):
    """Accept exact request/FEN, complete legal PVs and the requested depth only."""
    if lines is None:
        return False
    if (lines.requested_line_count != settings.generator.candidate_line_count
            or lines.analysis_profile != settings.generator.engine.profile_id
            or lines.fen != fen or lines.engine_identity != request_identity(settings.generator, root_moves)
            or tuple(lines.generation_metadata.get('root_moves', ())) != tuple(root_moves)
            or lines.generation_metadata.get('complete') is not True):
        return False
    if lines.generation_metadata.get('terminal'):
        return chess.Board(fen).is_game_over()
    expected = min(settings.generator.candidate_line_count, len(root_moves) if root_moves else chess.Board(fen).legal_moves.count())
    return (len(lines.lines) == expected and all(
        (settings.generator.engine.depth is None or line.depth >= settings.generator.engine.depth)
        and (not root_moves or line.move_uci in root_moves) for line in lines.lines))


@dataclass(frozen=True)
class MoveQuality:
    move: QualityMove
    phase: GamePhase
    state: str
    evidence_complete: bool = False
    best_move: str | None = None
    best_san: str | None = None
    best_move_match: bool | None = None
    top_n_match: bool | None = None
    before_eval: LineScore | None = None
    played_continuation_eval: LineScore | None = None
    eval_loss_cp: int | None = None
    accuracy: float | None = None
    raw_difference_cp: int | None = None
    evidence_profile: str = ''
    best_request_identity: str = ''
    played_request_identity: str = ''
    result_identity: str = ''
    provenance: str = 'same_root_conditioned_scores'


def assess_move(move, root, played_lines=None, settings=MoveQualitySettings()):
    """No search or writes. Scores describe continuations from this one decision FEN."""
    board = chess.Board(move.fen)
    board.parse_uci(move.played_move)
    fields = dict(move=move, phase=game_phase(board, settings.phase),
                  evidence_profile=f'{settings.generator.engine.engine_name} {settings.generator.engine.engine_version} · depth {settings.generator.engine.depth} · {settings.generator.candidate_line_count} line(s)',
                  best_request_identity=settings.raw_identity, result_identity=settings.currentness_identity)
    if not compatible_lines(root, move.fen, settings):
        return MoveQuality(state='missing_best_evidence', **fields)
    if not root.lines:
        return MoveQuality(state='terminal_before_move', evidence_complete=True, **fields)
    best = root.lines[0]
    chosen = next((line for line in root.lines if line.move_uci == move.played_move), None)
    fields.update(best_move=best.move_uci, best_san=best.move_san,
                  best_move_match=best.move_uci == move.played_move,
                  top_n_match=(chosen is not None) if settings.generator.candidate_line_count > 1 else None,
                  before_eval=best.score.pov('white'))
    if chosen is None:
        restriction = (move.played_move,)
        if not compatible_lines(played_lines, move.fen, settings, restriction) or not played_lines.lines:
            return MoveQuality(state='missing_played_evidence', **fields)
        chosen = played_lines.lines[0]
    loss = mover_loss(best.score, chosen.score, move.mover_color, settings)
    return MoveQuality(state=loss.state, evidence_complete=True,
                       played_continuation_eval=chosen.score.pov('white'),
                       played_request_identity=chosen.engine_identity,
                       eval_loss_cp=loss.eval_loss_cp, accuracy=loss.accuracy,
                       raw_difference_cp=loss.raw_difference_cp, **fields)


@dataclass(frozen=True)
class QualityAggregate:
    total_moves: int
    evaluated_moves: int
    accuracy: float | None
    best_move_rate: float | None
    best_move_count: int
    best_evidence_moves: int
    average_loss_cp: float | None
    median_loss_cp: float | None
    cp_loss_moves: int

    @property
    def complete(self):
        return bool(self.total_moves) and self.total_moves == self.evaluated_moves


def aggregate(values):
    values = tuple(values)
    scores = [v.accuracy for v in values if v.accuracy is not None]
    cp = [v.eval_loss_cp for v in values if v.eval_loss_cp is not None]
    matches = [v.best_move_match for v in values if v.best_move_match is not None]
    return QualityAggregate(len(values), len(scores), mean(scores) if scores else None,
                            100*sum(matches)/len(matches) if matches else None,
                            sum(matches), len(matches), mean(cp) if cp else None,
                            median(cp) if cp else None, len(cp))


@dataclass(frozen=True)
class GameQuality:
    moves: tuple[MoveQuality, ...]
    user_color: str

    def __post_init__(self):
        if self.user_color not in {"white", "black"}:
            raise ValueError("Explicit user color required")
        object.__setattr__(self, "moves", tuple(self.moves))

    @property
    def overall(self):
        return aggregate(self.moves)

    def for_color(self, color):
        return aggregate(v for v in self.moves if v.move.mover_color == color)

    @property
    def user(self):
        return self.for_color(self.user_color)

    @property
    def opponent(self):
        return self.for_color('black' if self.user_color == 'white' else 'white')

    def for_phase(self, phase, color=None):
        return aggregate(v for v in self.moves if v.phase == phase and (color is None or v.move.mover_color == color))
