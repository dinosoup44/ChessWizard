"""Deterministic art fixtures, independent of games, engines and analyzers."""
from dataclasses import dataclass
import chess


@dataclass(frozen=True)
class PreviewState:
    name: str
    fen: str


def piece_rows(piece):
    return f"{piece.lower()*8}/8/8/8/8/8/8/{piece.upper()*8} w - - 0 1"


PREVIEW_STATES = (
    PreviewState("Empty board","8/8/8/8/8/8/8/8 w - - 0 1"),
    PreviewState("Starting position",chess.STARTING_FEN),
    PreviewState("Pawns only","8/pppppppp/8/8/8/8/PPPPPPPP/8 w - - 0 1"),
    PreviewState("Knights only",piece_rows("n")),
    PreviewState("Bishops only",piece_rows("b")),
    PreviewState("Rooks only",piece_rows("r")),
    PreviewState("Kings + queens","q2qk2q/8/8/8/8/8/8/Q2QK2Q w - - 0 1"),
    PreviewState("Crowded center","r2q1rk1/pp1nbppp/2p1pn2/3p4/2PP4/2NBPN2/PPQ2PPP/R1B2RK1 w - - 0 9"),
    PreviewState("Edge / corner stress","rnbqkbnr/p6p/8/8/8/8/P6P/RNBQKBNR w - - 0 1"),
    PreviewState("Mixed realistic position","r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 b kq - 0 5"),
)
