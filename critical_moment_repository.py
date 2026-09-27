"""Read-only exact-FEN score lookup; no engine fallback or cache mutations."""
import json
import chess
from critical_moment_context import EvaluationEvidence


class ContextEvaluationReader:
    def __init__(self, connection):
        self.connection = connection

    def _scores(self, fen, player):
        cursor = self.connection.execute("SELECT cache_id,engine_name,engine_version,analysis_profile,analysis_version,limit_type,limit_value,score_type,score_cp,mate,score_pov FROM engine_position_cache WHERE fen=?", (fen,))
        result = {}
        for row in cursor:
            key = json.dumps(list(row[1:7]),separators=(",",":"))
            if row[10] not in ("white","black"):
                continue
            sign = 1 if (row[10] == "white") == player else -1
            cp, mate_for_player = None,None
            if row[7] == "cp" and type(row[8]) is int:
                cp = sign * row[8]
            elif row[7] == "mate" and type(row[9]) is int:
                if row[9] == 0:
                    board = chess.Board(fen)
                    if not board.is_checkmate(): continue
                    mate_for_player = board.turn != player
                else:
                    mate_for_player = sign * row[9] > 0
            else:
                continue
            score = EvaluationEvidence(fen,key,f"engine_position_cache:{row[0]}",cp,mate_for_player)
            if key in result:
                result[key] = None  # Conflicting/duplicate identities are uncertainty, not a selection rule.
            else:
                result[key] = score
        return {k:v for k,v in result.items() if v is not None}

    def pair(self, before_fen, after_fen, player, *, profile="tactic_verify_v1"):
        """Both scores must share complete stored engine/profile/budget identity."""
        before, after = self._scores(before_fen,player),self._scores(after_fen,player)
        keys = sorted(k for k in before.keys() & after.keys() if json.loads(k)[2] == profile)
        if len(keys) != 1:
            return None,None
        key = keys[0]
        return before[key],after[key]
