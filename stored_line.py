"""Stored SAN replay data, without engine analysis or persistence."""
from dataclasses import dataclass
import chess


@dataclass(frozen=True)
class StoredLine:
    base_fen: str | None
    moves: tuple[str, ...]
    source_candidate_id: int | None
    raw_text: str
    positions: tuple[str, ...] = ()
    moves_uci: tuple[str, ...] = ()
    validation_error: str | None = None

    @property
    def display_text(self):
        return " → ".join(self.moves) if self.positions else self.raw_text

    @classmethod
    def from_san(cls, base_fen, text, candidate_id=None):
        text = text.strip() if text else ""
        tokens = tuple(text.split())
        if not tokens or not base_fen:
            return cls(base_fen, tokens, candidate_id, text)
        try:
            board = chess.Board(base_fen)
            if not board.is_valid():
                raise ValueError("Stored line base position is invalid")
            positions, sans, ucis = [board.fen()], [], []
            for token in tokens:
                move = board.parse_san(token)
                sans.append(board.san(move))
                ucis.append(move.uci())
                board.push(move)
                positions.append(board.fen())
            return cls(base_fen, tuple(sans), candidate_id, text, tuple(positions), tuple(ucis))
        except ValueError as error:
            # Preserve incomplete/legacy text for display, but expose no partial
            # replay positions as a validated line.
            return cls(base_fen, tokens, candidate_id, text, validation_error=str(error))

    def position_at(self, index):
        if not self.positions:
            raise ValueError("This stored line is not available for legal replay")
        if not 0 <= index < len(self.positions):
            raise IndexError(index)
        return self.positions[index]
