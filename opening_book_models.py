"""Portable authoring graph contracts; no engine, UI or persistence dependencies."""
from dataclasses import dataclass, asdict
import hashlib
import json
import chess
import chess.polyglot
from opening_repertoire import RepertoireSide, read_repertoire_side

SCHEMA_VERSION = 2
MIN_WEIGHT, MAX_WEIGHT = 1, 100


def json_metadata(value="{}"):
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("Metadata must be a JSON object.")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def text(value, name, *, required=False):
    if not isinstance(value, str) or len(value) > 65536 or (required and not value.strip()):
        raise ValueError(f"{name} must be {'nonempty ' if required else ''}text (at most 64 KiB).")
    return value


def standard_board(fen):
    board = fen.copy(stack=False) if isinstance(fen, chess.Board) else chess.Board(fen)
    if type(board) is not chess.Board or board.chess960 or not board.is_valid():
        raise ValueError("Opening Book V1 requires a valid standard-chess position.")
    return board


@dataclass(frozen=True)
class PositionIdentity:
    canonical_fen: str
    polyglot_key: str
    side_to_move: str


def position_identity(fen):
    """Polyglot state: pieces, turn, castling and pseudo-capturable EP; no clocks.

    X-FEN retains EP for an adjacent pinned pawn too, matching Polyglot's hash.
    The full canonical state, not the 64-bit hash alone, deduplicates positions.
    """
    board = standard_board(fen)
    fields = board.fen(en_passant="xfen").split()[:4]
    canonical = " ".join((*fields, "0", "1"))
    return PositionIdentity(canonical, f"{chess.polyglot.zobrist_hash(board):016x}",
                            "white" if board.turn else "black")


@dataclass(frozen=True)
class BookDetails:
    """Describe an authored book, with optional explicit side in existing metadata.

    Args:
        name: Display name.
        description: Author description.
        version: Author-maintained version.
        status: Draft, active or archived lifecycle.
        metadata_json: JSON object; repertoire_side, when present, is white/black/both.
    """
    name: str
    description: str = ""
    version: str = "0.1"
    status: str = "draft"
    metadata_json: str = "{}"

    def __post_init__(self) -> None:
        """Validate author fields and explicit repertoire-side metadata."""
        text(self.name, "Book name", required=True)
        text(self.description, "Description")
        text(self.version, "Version", required=True)
        if self.status not in ("draft", "active", "archived"):
            raise ValueError("Status must be draft, active or archived.")
        object.__setattr__(self, "metadata_json", json_metadata(self.metadata_json))
        read_repertoire_side(self.metadata_json)

    @property
    def repertoire_side(self) -> RepertoireSide | None:
        """Read the intended side without guessing legacy-book intent.

        Returns:
            Explicit White, Black or Both; None when unspecified.

        Raises:
            ValueError: Metadata contains an invalid side.
        """
        return read_repertoire_side(self.metadata_json)


@dataclass(frozen=True)
class MoveDetails:
    weight: int = 50
    preferred: bool = False
    active: bool = True
    move_note: str = ""
    instructional_note: str = ""
    metadata_json: str = "{}"

    variation_name: str = ""
    variation_description: str = ""

    def __post_init__(self):
        text(self.variation_name, "Variation name")
        text(self.variation_description, "Variation description")
        if type(self.weight) is not int or not MIN_WEIGHT <= self.weight <= MAX_WEIGHT:
            raise ValueError("Book weight must be an integer from 1 to 100.")
        if type(self.preferred) is not bool or type(self.active) is not bool:
            raise ValueError("Preferred and active must be Boolean.")
        if self.preferred and not self.active:
            raise ValueError("An inactive branch cannot be preferred.")
        text(self.move_note, "Move note")
        text(self.instructional_note, "Instructional note")
        object.__setattr__(self, "metadata_json", json_metadata(self.metadata_json))


@dataclass(frozen=True)
class SourceDetails:
    title: str = ""
    author: str = ""
    edition: str = ""
    chapter: str = ""
    page: str = ""
    private_note: str = ""

    def __post_init__(self):
        for name, value in asdict(self).items():
            text(value, name)
        if not any(asdict(self).values()):
            raise ValueError("Enter at least one source reference field.")


@dataclass(frozen=True)
class OpeningBook:
    """Hold persisted author metadata and stable book identity.

    Args:
        book_id: Stable library-local ID.
        root_position_id: Root of the authored graph.
        name: Display name.
        description: Author description.
        version: Author version.
        status: Author lifecycle state.
        revision: Repository revision for currentness.
        metadata_json: Extensible metadata including optional repertoire_side.
        created_at: Original creation timestamp.
        updated_at: Last author edit timestamp.
    """
    book_id: int
    root_position_id: int
    name: str
    description: str
    version: str
    status: str
    revision: int
    metadata_json: str
    created_at: str
    updated_at: str

    @property
    def repertoire_side(self) -> RepertoireSide | None:
        """Read the intended side without guessing legacy-book intent.

        Returns:
            Explicit White, Black or Both; None when unspecified.

        Raises:
            ValueError: Metadata contains an invalid side.
        """
        return read_repertoire_side(self.metadata_json)


@dataclass(frozen=True)
class OpeningPosition:
    position_id: int
    canonical_fen: str
    polyglot_key: str
    side_to_move: str
    position_note: str
    metadata_json: str


@dataclass(frozen=True)
class OpeningMove:
    move_id: int
    book_id: int
    from_position_id: int
    move_uci: str
    san: str
    to_position_id: int
    weight: int
    preferred: bool
    active: bool
    move_note: str
    instructional_note: str
    metadata_json: str
    variation_name: str = ""
    variation_description: str = ""


@dataclass(frozen=True)
class SourceReference:
    source_ref_id: int
    book_id: int
    position_id: int
    move_id: int | None
    title: str
    author: str
    edition: str
    chapter: str
    page: str
    private_note: str


@dataclass(frozen=True)
class BookSnapshot:
    book: OpeningBook
    positions: tuple[OpeningPosition, ...]
    moves: tuple[OpeningMove, ...]
    sources: tuple[SourceReference, ...]

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()

    def position(self, position_id):
        return next(p for p in self.positions if p.position_id == position_id)

    def branches(self, position_id, *, active_only=False):
        return tuple(m for m in self.moves if m.from_position_id == position_id and (m.active or not active_only))

    def reachable(self, *, active_only=True):
        """Only root-reachable theory participates in lookup/export; cycles terminate."""
        visited, pending = set(), [self.book.root_position_id]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            pending.extend(m.to_position_id for m in self.branches(current, active_only=active_only))
        return frozenset(visited)

