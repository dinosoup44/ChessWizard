"""Shared PGN parsing/validation for the existing provider normalizers."""
from datetime import datetime
import io
import re
import chess.pgn


class EmptyImportedGame(ValueError):
    """Signal an import record with no legal registered moves; skip without insertion."""


def has_legal_move(game: chess.pgn.Game) -> bool:
    """Determine whether a parsed record contains a legal registered move.

    Args:
        game: Parsed standard-chess PGN.

    Returns:
        Whether the legal main line contains at least one move.
    """
    board = game.board()
    move = next(iter(game.mainline_moves()), None)
    return board.is_valid() and move is not None and move in board.legal_moves


class _RecordingReader:
    def __init__(self, stream):
        self.stream = stream
        self.lines = []

    def readline(self):
        line = self.stream.readline()
        self.lines.append(line)
        return line


def split_pgn_games(text_or_stream):
    """Retain each raw PGN while consuming a possibly non-seekable provider stream."""
    stream = io.StringIO(text_or_stream) if isinstance(text_or_stream, str) else text_or_stream
    while True:
        reader = _RecordingReader(stream)
        game = chess.pgn.read_game(reader)
        if game is None:
            return
        yield game, "".join(reader.lines)


def played_timestamp(headers):
    """Store UTC date/time for new games; leave old rows unchanged."""
    date = headers.get("UTCDate", headers.get("Date", ""))
    clock = headers.get("UTCTime", "00:00:00")
    try:
        return datetime.strptime(date + " " + clock, "%Y.%m.%d %H:%M:%S").isoformat() + "Z"
    except ValueError:
        return date or None


def validate_game(game: chess.pgn.Game, username: str, identity: str | None, raw_pgn: str) -> None:
    """Validate a provider game before any account, game or move insertion.

    Args:
        game: Parsed PGN with its original parse errors.
        username: Account being imported.
        identity: Canonical provider game ID.
        raw_pgn: Original provider PGN including its result token.

    Raises:
        EmptyImportedGame: No legal registered move exists; count as skipped.
        ValueError: Identity, players, variant or completed PGN is invalid.
    """
    if not has_legal_move(game):
        raise EmptyImportedGame('Game has no legal registered moves')
    if not identity:
        raise ValueError("Missing canonical source game ID")
    if not re.search(r"(?:1-0|0-1|1/2-1/2)\s*(?:\{[^}]*\}\s*)*$", raw_pgn):
        raise ValueError("Game is unfinished or its download is incomplete")
    if game.errors:
        raise ValueError("Malformed PGN: illegal or unparseable move")
    players = [game.headers.get(color, "").casefold() for color in ("White", "Black")]
    if username.casefold() not in players:
        raise ValueError("Account is not a player in this game")
    board = game.board()
    if board.uci_variant != "chess" or board.chess960 or not board.is_valid():
        raise ValueError("Unsupported variant or invalid starting position")

