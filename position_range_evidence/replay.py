"""One legal replay with stable original identities; no engine or persistence dependencies."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import chess
from .models import (PieceIdentity, MoveEvent, CaptureEvent, PromotionEvent, CheckEvent,
                     PieceIdentityTransition, TargetFate, AttackerSurvival, PositionEvidence, RangeEvidence,
                     RelevantRecapture)
from .material import configured_values, material_totals, material_transition
from .terminal import terminal_state, supplied_history_complete
from .attacks import legal_captures, attack_state, relevant_recaptures
from board_analysis import capture_square


class IllegalRangeError(ValueError):
    """A range failed validation at a 1-based ply; no partial result is returned."""


def square_index(square: int | str) -> int:
    result = chess.parse_square(square) if isinstance(square, str) else square
    if type(result) is not int or result not in chess.SQUARES:
        raise ValueError(f"Invalid square: {square!r}")
    return result


def source_board(source: str | chess.Board) -> chess.Board:
    board = chess.Board(source) if isinstance(source, str) else source.copy(stack=True)
    if type(board) is not chess.Board or not board.is_valid():
        raise ValueError("Expected a valid standard/Chess960 board, not a chess variant")
    return board


def initial_identities(board: chess.Board) -> dict[int, PieceIdentity]:
    return {s: PieceIdentity(s, p.piece_type, p.color) for s, p in sorted(board.piece_map().items())}


@dataclass(slots=True)
class _PieceState:
    square: int | None
    piece_type: int
    capture_ply: int | None = None
    captured_by: PieceIdentity | None = None
    moves: int = 0
    promotions: list[PromotionEvent] = field(default_factory=list)


def _castling_destinations(board: chess.Board, move: chess.Move) -> tuple[int, int, int]:
    kingside = board.is_kingside_castling(move)
    rank = chess.square_rank(move.from_square)
    rooks = [s for s in chess.scan_forward(board.clean_castling_rights())
             if chess.square_rank(s) == rank and (s > move.from_square) == kingside]
    if len(rooks) != 1:
        raise IllegalRangeError("Castling requires one eligible rook on the selected flank")
    return chess.square(6 if kingside else 2, rank), rooks[0], chess.square(5 if kingside else 3, rank)


def _apply_move(board, move, ply, identities, states, values) -> MoveEvent:
    actor, moving_type = identities[move.from_square], board.piece_type_at(move.from_square)
    san, castle, ep = board.san(move), board.is_castling(move), board.is_en_passant(move)
    destination, rook_source, rook_dest = (_castling_destinations(board, move) if castle
                                           else (move.to_square, None, None))
    victim_square = None if castle else capture_square(board, move)
    capture, promotion, transitions = None, None, []
    if victim_square is not None:
        victim = identities[victim_square]
        victim_type = board.piece_type_at(victim_square)
        capture = CaptureEvent(ply, actor, victim, victim_type, victim.color, victim_square,
                               destination, values[victim_type], ep)
        states[victim].capture_ply, states[victim].captured_by = ply, actor
        transitions.append(PieceIdentityTransition(ply, victim, victim_square, None,
                                                   victim_type, victim_type, "capture"))
    final_type = move.promotion or moving_type
    if move.promotion:
        promotion = PromotionEvent(ply, actor, destination, moving_type, final_type,
                                   values[final_type] - values[moving_type])
        states[actor].promotions.append(promotion)
    transitions.append(PieceIdentityTransition(ply, actor, move.from_square, destination,
        moving_type, final_type, "castling_king" if castle else "promotion" if promotion else "move"))
    if castle:
        transitions.append(PieceIdentityTransition(ply, identities[rook_source], rook_source, rook_dest,
                                                   chess.ROOK, chess.ROOK, "castling_rook"))
    # Clear every source first: Chess960 king/rook destinations can overlap their old squares.
    for transition in transitions:
        del identities[transition.from_square]
    for transition in transitions:
        state = states[transition.piece]
        state.square, state.piece_type = transition.to_square, transition.to_type
        if transition.to_square is not None:
            identities[transition.to_square] = transition.piece
            state.moves += 1
    board.push(move)
    check = CheckEvent(ply, board.turn, tuple(board.checkers())) if board.is_check() else None
    return MoveEvent(ply, move.uci(), san, actor, move.from_square, destination, castle,
                     capture, promotion, check, tuple(transitions))


class LegalReplay:
    """Isolated reusable ledger. Returned boards are copies; all public evidence is immutable.

    Intermediate queries reconstruct only the requested endpoint, never all intermediate attack maps.
    Move counts include castling participation, even for a stationary Chess960 king/rook.
    """
    __slots__ = ("_start_fen", "_board", "_initial", "_identities", "_states", "_events",
                 "_values", "_before", "_history_complete")

    def __init__(self, start: str | chess.Board, moves_uci: Iterable[str], *,
                 moves_san: Iterable[str] | None = None, piece_values: Mapping[int, int] | None = None,
                 history_complete: bool | None = None) -> None:
        board = source_board(start)
        self._history_complete = supplied_history_complete(board, history_complete)
        self._start_fen = board.fen()
        self._values = configured_values(piece_values)
        self._before = material_totals(board, self._values)
        self._initial = initial_identities(board)
        self._identities = dict(self._initial)
        self._states = {i: _PieceState(s, i.initial_piece_type) for s, i in self._initial.items()}
        ucis, sans = tuple(moves_uci), None if moves_san is None else tuple(moves_san)
        if sans is not None and len(sans) != len(ucis):
            raise IllegalRangeError("SAN and UCI ranges must have the same length")
        events = []
        for ply, uci in enumerate(ucis, 1):
            try:
                move = board.parse_uci(uci)
                if not move or not board.is_legal(move):
                    raise ValueError("Null and illegal moves are not evidence")
                if sans is not None and (board.parse_san(sans[ply - 1]) != move or
                                         board.san(move) != sans[ply - 1]):
                    raise ValueError("SAN must match the canonical SAN for the UCI move")
            except (ValueError, TypeError) as exc:
                raise IllegalRangeError(f"Illegal range at ply {ply} ({uci!r}): {exc}") from exc
            events.append(_apply_move(board, move, ply, self._identities, self._states, self._values))
        self._events, self._board = tuple(events), board

    @property
    def events(self) -> tuple[MoveEvent, ...]:
        return self._events

    def identity_at_start(self, square: int | str) -> PieceIdentity:
        """Empty original squares raise KeyError; identities are local to this source position."""
        return self._initial[square_index(square)]

    def board_at(self, ply: int | None = None) -> chess.Board:
        """Return an independent board after `ply` moves (zero means the source)."""
        count = self._ply(ply)
        board = self._board.copy(stack=True)
        for _ in range(len(self._events) - count):
            board.pop()
        return board

    def _ply(self, ply):
        count = len(self._events) if ply is None else ply
        if type(count) is not int or not 0 <= count <= len(self._events):
            raise ValueError("Ply must be within the replay, inclusive")
        return count

    def _position(self, ply=None):
        count = self._ply(ply)
        identities = dict(self._identities)
        for event in reversed(self._events[count:]):
            for transition in event.transitions:
                if transition.to_square is not None:
                    del identities[transition.to_square]
            for transition in event.transitions:
                identities[transition.from_square] = transition.piece
        board = self.board_at(count)
        return board, identities, legal_captures(board, identities, self._values)

    def position_evidence(self, *, ply: int | None = None,
                          squares: Iterable[int | str] = ()) -> PositionEvidence:
        """Query selected squares, retaining original identities at intermediate endpoints."""
        selected = tuple(dict.fromkeys(square_index(s) for s in squares))
        if selected:
            board, identities, captures = self._position(ply)
        else:
            board, identities, captures = self.board_at(ply), {}, ()
        return PositionEvidence(board.fen(), board.turn, material_totals(board, self._values),
            terminal_state(board, history_complete=self._history_complete),
            tuple(attack_state(board, s, identities, captures) for s in selected))

    def _relations(self, captures, targets, count, lookback):
        if type(lookback) is not int or lookback < 0:
            raise ValueError("Recapture lookback must be a nonnegative ply count")
        attacker = self._events[0].actor if count else None
        participants = set(targets) | ({attacker} if attacker else set())
        for event in self._events[:count]:
            c = event.capture
            if c and (c.capturer in participants or c.victim in participants):
                participants.update((c.capturer, c.victim))
        recent = [square for e in self._events[max(0, count - lookback):count] if e.capture
                  for square in (e.capture.square, e.capture.destination)]
        return relevant_recaptures(captures, attacker=attacker, targets=targets,
            recent_capture_squares=recent, exchange_participants=participants)

    def relevant_recaptures(self, *, ply: int | None = None, track_squares: Iterable[int | str] = (),
                            lookback_plies: int = 1) -> tuple[RelevantRecapture, ...]:
        """Query an intermediate/endpoint actual-side capture, with explicit recency scope."""
        _, _, captures = self._position(ply)
        targets = tuple(self.identity_at_start(s) for s in track_squares)
        return self._relations(captures, targets, self._ply(ply), lookback_plies)

    def evidence(self, *, track_squares: Iterable[int | str] = (), material_snapshots: bool = False,
                 recapture_lookback_plies: int = 1) -> RangeEvidence:
        """Compose all six helpers from one ledger; attack facts are limited to requested pieces."""
        targets = tuple(dict.fromkeys(self.identity_at_start(s) for s in track_squares))
        attacker = self._events[0].actor if self._events else None
        requested = tuple(dict.fromkeys(targets + ((attacker,) if attacker else ())))
        board, identities, captures = self._position()
        terminal = terminal_state(board, history_complete=self._history_complete)
        fates = []
        for identity in requested:
            state = self._states[identity]
            attack = attack_state(board, state.square, identities, captures) if state.square is not None else None
            fates.append(TargetFate(identity, state.square, state.piece_type, state.capture_ply,
                state.captured_by, state.moves, tuple(state.promotions), attack, terminal.state,
                state.piece_type == chess.KING and state.square is not None and
                identity.color == board.turn and board.is_check()))
        relevant = self._relations(captures, targets, len(self._events), recapture_lookback_plies)
        survival = None
        if attacker:
            fate = next(f for f in fates if f.piece == attacker)
            involving = tuple(r for r in relevant if r.capture.capturer == attacker or r.capture.victim == attacker)
            survival = AttackerSurvival(fate, self._events[0].to_square, fate.move_count > 1, involving)
        material = material_transition(self._before, self._events, self._values, snapshots=material_snapshots)
        return RangeEvidence(self._start_fen, board.fen(), self._events, material, tuple(fates),
                             survival, terminal, relevant)


def analyze_range(start_fen: str | chess.Board, moves_uci: Iterable[str], *,
                  track_squares: Iterable[int | str] = (), moves_san: Iterable[str] | None = None,
                  piece_values: Mapping[int, int] | None = None, history_complete: bool | None = None,
                  material_snapshots: bool = False, recapture_lookback_plies: int = 1) -> RangeEvidence:
    """Replay once and compose immutable evidence; no partial result survives illegal input."""
    return LegalReplay(start_fen, moves_uci, moves_san=moves_san, piece_values=piece_values,
        history_complete=history_complete).evidence(track_squares=track_squares,
        material_snapshots=material_snapshots, recapture_lookback_plies=recapture_lookback_plies)


def analyze_position(position: str | chess.Board, *, squares: Iterable[int | str] = (),
                     piece_values: Mapping[int, int] | None = None,
                     history_complete: bool | None = None) -> PositionEvidence:
    """Position-only facts; unselected attack maps are not constructed."""
    return LegalReplay(position, (), piece_values=piece_values,
                       history_complete=history_complete).position_evidence(squares=squares)
