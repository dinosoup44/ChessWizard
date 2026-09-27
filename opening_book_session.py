"""Frontend-independent pending move and navigation state over an authored graph."""
import chess
from opening_book_models import MoveDetails, position_identity


class OpeningBookSession:
    def __init__(self, service, book_id):
        self.service, self.book_id = service, book_id
        self.history, self.cursor, self.pending = (), 0, None
        self.refresh()

    def refresh(self):
        self.snapshot = self.service.repository.snapshot(self.book_id)
        self._replay()

    def _replay(self):
        self.position_id = self.snapshot.book.root_position_id
        self.board = chess.Board(self.snapshot.position(self.position_id).canonical_fen)
        edges = {m.move_id:m for m in self.snapshot.moves}
        for edge_id in self.history[:self.cursor]:
            edge = edges.get(edge_id)
            if edge is None or edge.from_position_id != self.position_id:
                raise ValueError("Navigation path changed; return to root.")
            self.board.push_uci(edge.move_uci)
            self.position_id = edge.to_position_id

    def breadcrumb(self) -> str:
        """Describe the active path, keeping variation labels separate from preference."""
        edges = {m.move_id: m for m in self.snapshot.moves}
        board = chess.Board(self.snapshot.position(self.snapshot.book.root_position_id).canonical_fen)
        names, moves = [], []
        for move_id in self.history[:self.cursor]:
            edge = edges[move_id]
            if edge.variation_name:
                names.append(edge.variation_name)
            prefix = f"{board.fullmove_number}." if board.turn else (f"{board.fullmove_number}…" if not moves else "")
            moves.append(prefix + edge.san)
            board.push_uci(edge.move_uci)
        return " > ".join((self.snapshot.book.name, *names)) + "\n" + (" ".join(moves) or "Book start")

    def stage(self, move_uci):
        if self.pending:
            raise ValueError("Save or discard the pending move first.")
        move = self.board.parse_uci(move_uci)
        if not move or move not in self.board.legal_moves:
            raise ValueError("Only legal chess moves can be staged.")
        self.pending = move.uci()
        return self.board.san(chess.Move.from_uci(self.pending))

    def stage_notation(self, notation):
        try:
            move = self.board.parse_uci(notation)
        except ValueError:
            move = self.board.parse_san(notation)
        return self.stage(move.uci())

    def discard(self):
        self.pending = None

    def save(self, details=MoveDetails()):
        if not self.pending:
            raise ValueError("There is no pending move.")
        edge_id = self.service.save_move(self.book_id, self.board.fen(), self.pending, details)
        self.pending = None
        self.snapshot = self.service.repository.snapshot(self.book_id)
        self.follow(edge_id)
        return edge_id

    def _require_saved(self):
        if self.pending:
            raise ValueError("Save or discard the pending move before navigation.")

    def follow(self, edge_id):
        self._require_saved()
        if edge_id not in {m.move_id for m in self.snapshot.branches(self.position_id)}:
            raise ValueError("Choose a saved branch at this position.")
        self.history = (*self.history[:self.cursor], edge_id)
        self.cursor += 1
        self._replay()

    def back(self):
        self._require_saved()
        self.cursor = max(0, self.cursor-1)
        self._replay()

    def forward(self):
        self._require_saved()
        self.cursor = min(len(self.history), self.cursor+1)
        self._replay()

    def root(self):
        self._require_saved()
        self.cursor = 0
        self._replay()

    def go_to(self, path):
        self._require_saved()
        before = self.history, self.cursor
        try:
            self.history, self.cursor = tuple(path), len(path)
            self._replay()
        except (ValueError, TypeError):
            self.history, self.cursor = before
            self._replay()
            raise

