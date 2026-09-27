"""Shared MultiPV generation with injected engine access; no persistence."""
import time
from typing import Any, Protocol
import chess
import chess.engine
from evidence_errors import IncompleteLineEvidence
from candidate_lines import CandidateLine, CandidateLineSet, LineScore, to_data
from analysis_settings import GeneratorSettings, identity
from candidate_line_request import normalized_root_moves, request_identity


class CandidateLineEngine(Protocol):
    """Provide shared engine access without exposing persistence or UI."""
    def analyse(self, board: chess.Board, limit: chess.engine.Limit, **options: Any) -> chess.engine.InfoDict | list[chess.engine.InfoDict]:
        """Execute the caller's exact engine request.

        Args:
            board: Request root.
            limit: Unchanged search budget.
            options: MultiPV, restrictions and engine options.

        Returns:
            Raw engine information before exact-evidence validation.
        """
        ...


class CandidateLineGenerator:
    """Generate exact-score legal PVs without persistence.

    Args:
        engine: Injected shared engine service.
    """
    def __init__(self, engine: CandidateLineEngine) -> None:
        """Bind shared engine access without starting a request.

        Args:
            engine: Existing engine service.
        """
        self.engine = engine

    def generate(self, fen: str, settings: GeneratorSettings = GeneratorSettings(), *,
                 root_moves: tuple[str, ...] = ()) -> CandidateLineSet:
        """Generate one exact-score request, retaining conservative uncertainty.

        Args:
            fen: Legal root position.
            settings: Shared raw-evidence settings.
            root_moves: Optional exact move restrictions.

        Returns:
            Validated line set, including terminal or explicitly incomplete sets.

        Raises:
            IncompleteLineEvidence: A returned bound cannot be used as an exact score.
            ValueError: Position, restriction, score or PV violates its contract.
        """
        board = chess.Board(fen)
        if not board.is_valid(): raise ValueError("Invalid position")
        side = "white" if board.turn else "black"
        root_moves = normalized_root_moves(root_moves)
        restricted = [board.parse_uci(uci) for uci in root_moves]
        config_id = request_identity(settings, root_moves)
        meta = {
            'source': 'engine_multipv',
            'history_scope': 'fen_only',
            'complete': True,
            'generator_settings': to_data(settings),
            'root_moves': list(root_moves),
        }
        if board.is_game_over():
            return CandidateLineSet(fen, side, settings.candidate_line_count, settings.engine.profile_id,
                config_id, (), {**meta, "terminal": True, "result": board.result()})
        engine = settings.engine
        start = time.perf_counter()
        infos = self.engine.analyse(board, chess.engine.Limit(depth=engine.depth, nodes=engine.nodes,
            time=engine.time_seconds), multipv=settings.candidate_line_count,
            options={"Threads": engine.threads, "Hash": engine.hash_mb}, game=object(),
            **({'root_moves': restricted} if restricted else {}))
        if not isinstance(infos, list): raise ValueError("MultiPV must return a list")
        lines = tuple(_normalize_line(info, settings, config_id)
                      for info in sorted(infos, key=lambda value: value.get('multipv', 1)))
        meta.update(elapsed_seconds=time.perf_counter()-start,
            complete=len(lines) == min(settings.candidate_line_count, len(restricted) if restricted else board.legal_moves.count()))
        if restricted and any(line.move_uci not in root_moves for line in lines):
            raise ValueError('Engine ignored requested root restriction')
        return CandidateLineSet(fen, side, settings.candidate_line_count, engine.profile_id, config_id, tuple(lines), meta)


def _normalize_line(info, settings, config_id):
    if info.get('lowerbound') or info.get('upperbound'):
        raise IncompleteLineEvidence('Bounded score is incomplete evidence')
    pv, raw_score = info.get('pv'), info.get('score')
    if not pv or raw_score is None:
        raise ValueError('Missing PV or score')
    white_score = raw_score.pov(chess.WHITE)
    mate = white_score.mate()
    owner = None
    if mate is not None:
        # MateGiven and Mate(0) have the same numeric distance and opposite owners.
        owner = 'white' if white_score > chess.engine.Cp(0) else 'black'
    score = LineScore(white_score.score(), mate, 'white', owner)
    return CandidateLine(
        rank=info.get('multipv', 1),
        move_uci=pv[0].uci(),
        score=score,
        pv_uci=tuple(move.uci() for move in pv),
        depth=info.get('depth'),
        engine_identity=config_id,
        analysis_version=settings.analysis_version,
        nodes=info.get('nodes'),
    )
