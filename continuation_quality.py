"""Cheap legal-PV facts and optional externally supplied continuation evidence."""
from dataclasses import dataclass
import math
import chess
from board_analysis import capture_square, material_balance
from candidate_lines import LineScore, to_data
from analysis_settings import MaterialValues, identity


def line_identity(fen, line):
    return identity({'fen': fen, 'move': line.move_uci, 'pv': line.pv_uci,
                     'engine': line.engine_identity, 'score': to_data(line.score)})


@dataclass(frozen=True)
class EvaluationSample:
    ply: int
    score: LineScore

    def __post_init__(self):
        if type(self.ply) is not int or self.ply < 0 or not isinstance(self.score, LineScore):
            raise ValueError('Invalid evaluation sample')


@dataclass(frozen=True)
class ContinuationEvidence:
    line_identity: str
    engine_identity: str
    source: str
    evaluations: tuple[EvaluationSample, ...] = ()
    settled: bool | None = None
    payoff_reached: bool | None = None
    defensive_narrowness: float | None = None
    line_remains_acceptable: bool | None = None

    def __post_init__(self):
        if not self.source or not self.line_identity or not self.engine_identity:
            raise ValueError('Evidence provenance required')
        object.__setattr__(self, 'evaluations', tuple(self.evaluations))
        for name in ('settled', 'payoff_reached', 'line_remains_acceptable'):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise ValueError('Boolean evidence required')
        n = self.defensive_narrowness
        if n is not None and (type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1):
            raise ValueError('Narrowness must be between zero and one')
        plies = [s.ply for s in self.evaluations]
        if plies != sorted(set(plies)):
            raise ValueError('Evaluation samples must be ordered and unique')


@dataclass(frozen=True)
class SemanticEvent:
    event_id: str
    component: str
    value: float
    source: str
    evidence: str

    def __post_init__(self):
        if not self.event_id or not self.source or not self.evidence:
            raise ValueError('Auditable event provenance required')
        if type(self.value) not in (int, float) or not math.isfinite(self.value) or not 0 <= self.value <= 1:
            raise ValueError('Event strength must be finite and between zero and one')


@dataclass(frozen=True)
class ContinuationQuality:
    eval_start: LineScore
    eval_peak_cp: int | None
    eval_end: LineScore | None
    eval_trend_cp: int | None
    material_start: int
    material_end: int
    material_gain: int
    material_low: int
    forcing_move_density: float
    continuation_length: int
    mate_pressure: str
    payoff_reached: bool | None
    settled: bool | None
    defensive_narrowness: float | None
    line_remains_acceptable: bool | None
    events: tuple[SemanticEvent, ...]


def inspect_continuation(fen, line, material=MaterialValues(), evidence=None):
    """Replay one PV; root engine score alone cannot prove endpoint quality or settlement."""
    board = chess.Board(fen)
    player, color = board.turn, 'white' if board.turn else 'black'
    if evidence is not None:
        if not isinstance(evidence, ContinuationEvidence) or evidence.line_identity != line_identity(fen, line) or evidence.engine_identity != line.engine_identity:
            raise ValueError('Incompatible continuation evidence')
        if any(sample.ply > len(line.pv_uci) for sample in evidence.evaluations):
            raise ValueError('Evaluation beyond PV')
    values = material.piece_values()
    balances = [material_balance(board, player, values)]
    captures, events, forcing = [], [], 0
    for ply, uci in enumerate(line.pv_uci, 1):
        move = board.parse_uci(uci)
        victim_square = capture_square(board, move)
        victim = board.piece_at(victim_square) if victim_square is not None else None
        actor, san = board.turn, board.san(move)
        forcing += int(board.is_capture(move) or board.gives_check(move) or bool(move.promotion))
        if victim and victim.color == player and victim.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            captures.append((ply, victim.piece_type, san))
        if actor == player and move.promotion and move.promotion != chess.QUEEN:
            events.append(SemanticEvent('underpromotion', 'rarity', 1, 'legal_pv_replay', f'{ply}: {san}'))
        board.push(move)
        balances.append(material_balance(board, player, values))
    for ply, piece, san in captures:
        # A directly recovered equal exchange is not a material investment.
        immediate_recovery = ply < len(line.pv_uci) and balances[ply + 1] >= balances[ply - 1]
        if balances[ply] < balances[0] and not immediate_recovery:
            events.append(SemanticEvent(chess.piece_name(piece) + '_material_investment', 'sacrifice_interest',
                min(1, values[piece] / material.queen), 'legal_pv_replay',
                f'{ply}: {san}; material balance {balances[ply]} cp. Observed investment, not verified sacrifice causality.'))
    samples = [s.score.pov(color) for s in evidence.evaluations] if evidence else []
    root_sample = bool(samples) and evidence.evaluations[0].ply == 0
    endpoint_sample = bool(samples) and evidence.evaluations[-1].ply == len(line.pv_uci)
    start = samples[0] if root_sample else line.score.pov(color)
    end = samples[-1] if endpoint_sample else None
    cp_samples = [s.score_cp for s in samples if s.score_cp is not None]
    trend = end.score_cp - start.score_cp if end is not None and start.score_cp is not None and end.score_cp is not None else None
    mate = line.score.mate_winner
    pressure = 'winning_mate' if mate == color else 'losing_mate' if mate else 'unknown'
    if mate:
        events.append(SemanticEvent(pressure, 'mate_interest', 1, 'engine_root_score',
            f'Owner {mate}; distance {abs(line.score.mate_score)} moves.'))
    # Root PV is not a freshly settled proof and supplies no evaluation trend.
    return ContinuationQuality(start, max(cp_samples) if cp_samples else None, end, trend,
        balances[0], balances[-1], balances[-1]-balances[0], min(balances),
        forcing / len(line.pv_uci), len(line.pv_uci), pressure,
        evidence.payoff_reached if evidence else None, evidence.settled if evidence else None,
        evidence.defensive_narrowness if evidence else None,
        evidence.line_remains_acceptable if evidence else None, tuple(events))
