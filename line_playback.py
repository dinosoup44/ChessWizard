"""Immutable presentation/playback of stored lines, without analysis or I/O."""
from dataclasses import dataclass, replace
import chess
from stored_line import StoredLine


@dataclass(frozen=True)
class ProofLineRow:
    move_number: int
    white: str = ""
    black: str = ""
    white_ply: int | None = None
    black_ply: int | None = None


def format_proof_line_rows(line: StoredLine) -> tuple[ProofLineRow, ...]:
    """Pair original SAN tokens using each validated position's turn and number."""
    LinePlaybackState(line)
    tokens = line.raw_text.split()
    if len(tokens) != len(line.moves_uci):
        raise ValueError("Stored notation and replay positions disagree")
    rows = []
    for ply, token in enumerate(tokens, 1):
        board = chess.Board(line.position_at(ply - 1))
        if not rows or rows[-1].move_number != board.fullmove_number:
            rows.append(ProofLineRow(board.fullmove_number))
        changes = {"white": token, "white_ply": ply} if board.turn else {"black": token, "black_ply": ply}
        rows[-1] = replace(rows[-1], **changes)
    return tuple(rows)


@dataclass(frozen=True)
class LinePlaybackState:
    """A projected ply never modifies its source line or an actual-game cursor."""
    line: StoredLine
    ply: int = 0

    def __post_init__(self):
        if not self.line.positions:
            raise ValueError(self.line.validation_error or "No stored line available for legal playback")
        if "0000" in self.line.moves_uci:
            raise ValueError("Null moves are not legal game moves")
        if not 0 <= self.ply < len(self.line.positions):
            raise ValueError("Line playback index out of bounds")

    @property
    def total_plies(self) -> int:
        return len(self.line.moves_uci)

    @property
    def fen(self) -> str:
        return self.line.position_at(self.ply)

    @property
    def last_move(self) -> chess.Move | None:
        return chess.Move.from_uci(self.line.moves_uci[self.ply - 1]) if self.ply else None

    def step(self, delta: int) -> "LinePlaybackState":
        return replace(self, ply=max(0, min(self.ply + delta, self.total_plies)))

    def reset(self) -> "LinePlaybackState":
        return replace(self, ply=0)
