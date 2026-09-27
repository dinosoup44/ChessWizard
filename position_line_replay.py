"""Read-only normalization of recorded single-PV evidence, not a raw-cache migration."""
import chess
from analysis_settings import identity
from candidate_lines import CandidateLine, CandidateLineSet, LineScore
from candidate_line_proof import IncompleteLineEvidence
from tactical_proof import validate_evaluation


class RecordedPositionReplay:
    """Keep legacy identity and unknown options explicit; never populate the new cache.

    The injected lookup must return the recorded request or raise on a miss.
    Returning the original envelope preserves cache IDs and existing feedback proofs.
    """
    def __init__(self, lookup, backbones):
        self.lookup, self.backbones = lookup, backbones
        self.records = {}
        self.sources = {}

    def evaluate(self, fen, profile):
        key = (fen, profile)
        if key in self.records:
            return self.records[key]
        raw = validate_evaluation(self.lookup(fen, profile))
        board = chess.Board(fen)
        depth = raw.get("depth")
        if type(depth) is not int or depth < 1:
            raise IncompleteLineEvidence("Recorded evidence has no verified depth")
        source = identity({"namespace": "recorded_single_pv_v1", "profile": profile,
            "request": {k: raw.get(k) for k in ("engine_name", "engine_version", "analysis_version", "limit_type", "limit_value")},
            "unrecorded": ["threads", "hash_mb", "root_restrictions", "multipv"]})
        pv = []
        position = board.copy(stack=False)
        for token in (raw.get("principal_variation") or "").split():
            move = position.parse_san(token); pv.append(move.uci()); position.push(move)
        if not pv and not board.is_game_over():
            raise IncompleteLineEvidence("Recorded evidence has no continuation")
        if pv and raw.get("best_move_uci") != pv[0]:
            raise ValueError("Recorded best move and PV disagree")
        score = LineScore(raw.get("score_cp") if raw["score_type"] == "cp" else None,
            raw.get("mate") if raw["score_type"] == "mate" else None,
            mate_winner=("black" if board.turn else "white") if board.is_checkmate() else None)
        lines = (CandidateLine(1, pv[0], score, tuple(pv), depth, source),) if pv else ()
        evidence = CandidateLineSet(fen, "white" if board.turn else "black", 1,
            "recorded:"+profile, source, lines, {"complete": True, "terminal": board.is_game_over(),
            "source": "recorded_single_pv", "new_cache_compatible": False})
        backbone = self.backbones[profile]
        approval = backbone.approve_recorded(evidence, source)
        if approval.state == "incomplete":
            raise IncompleteLineEvidence("Recorded evidence failed completeness")
        backbone.weigh(approval)
        self.sources[key] = source
        self.records[key] = raw
        return raw
