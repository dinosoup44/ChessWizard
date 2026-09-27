"""Immutable book-knowledge contracts, deliberately independent of engine quality."""
from dataclasses import dataclass, asdict
from typing import Literal
import hashlib
import json
from opening_book_models import OpeningMove, PositionIdentity


def identity(value) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class OpeningMatchPolicy:
    min_consecutive_plies: int = 4
    max_variation_contexts: int = 64
    max_named_depth: int = 32

    def __post_init__(self):
        for name,value in asdict(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer.")


@dataclass(frozen=True)
class BookProvenance:
    library_identity: str
    book_id: int
    book_name: str
    book_version: str
    book_revision: int
    content_identity: str
    membership_identity: str
    label_identity: str
    preference_identity: str
    policy_identity: str
    contract_version: int = 1

    def changes_from(self, previous) -> tuple[str, ...]:
        fields={"library_identity":"library", "book_id":"book", "book_version":"version",
                "membership_identity":"membership", "label_identity":"labels",
                "preference_identity":"preferences", "policy_identity":"policy",
                "content_identity":"content", "contract_version":"contract"}
        return tuple(label for field,label in fields.items() if getattr(self,field)!=getattr(previous,field))


@dataclass(frozen=True)
class NamedVariation:
    move_id: int
    name: str


@dataclass(frozen=True)
class VariationContext:
    paths: tuple[tuple[NamedVariation, ...], ...] = ()
    observed: bool = False
    complete: bool = True

    @property
    def ambiguous(self):
        return not self.complete or len(self.paths)>1

    @property
    def path(self):
        return self.paths[0] if len(self.paths)==1 and self.complete else ()

    @property
    def deepest_name(self):
        return self.path[-1].name if self.path else None


@dataclass(frozen=True)
class OpeningPositionLookup:
    provenance: BookProvenance
    identity: PositionIdentity
    position_id: int | None
    available_moves: tuple[OpeningMove, ...]
    preferred_move: OpeningMove | None
    variation_context: VariationContext

    @property
    def found(self):
        return self.position_id is not None


@dataclass(frozen=True)
class BookPositionVisit:
    after_ply: int
    position_id: int
    identity: PositionIdentity
    after_move: str


@dataclass(frozen=True)
class OpeningMoveAssessment:
    game_id: int | None
    move_id: int | None
    ply: int
    move_number: int
    actor_color: str
    played_uci: str
    played_san: str
    move_label: str
    position: PositionIdentity
    position_id: int | None
    after_position: PositionIdentity
    after_position_id: int | None
    played_move_in_book: bool
    played_weight: int | None
    available_moves: tuple[OpeningMove, ...]
    preferred_move: OpeningMove | None
    variation_before: VariationContext
    variation_after: VariationContext
    state: Literal['in_book','move_not_authored','continuation_not_authored','position_not_in_book']
    deviation: bool
    first_deviation: bool
    deviation_relation: str | None
    reentry: bool
    known_position_entry: bool
    provenance: BookProvenance

    @property
    def position_in_book(self):
        return self.position_id is not None


@dataclass(frozen=True)
class OpeningGameAssessment:
    """Hold immutable game replay facts and optional explicit family-entry timing.

    Args:
        game_id: Optional database-local game identifier.
        game_identity: Full namespace/move/currentness identity.
        provenance: Exact book and policy identities.
        user_color: Known owner side, or None.
        moves: Legal per-ply membership and deviation facts.
        known_book_positions: Active known-position visits in replay order.
        initial_variation: Named context at the actual starting board.
        final_variation: Last supported named context.
        followed_variations: Observed named paths.
        in_book_moves: Moves matching active authored edges after applicable entry.
        out_of_book_moves: Remaining actual moves.
        moves_with_alternatives: Decisions with authored alternatives.
        user_in_book_moves: Owner matches, or None if side is unknown.
        opponent_in_book_moves: Opponent matches, or None if side is unknown.
        first_deviation_ply: First eligible departure, when present.
        last_known_before_deviation: Last visit before the first departure.
        last_known_position: Last active known board.
        reentry_count: Known returns after an unknown interval.
        max_consecutive_in_book_plies: Longest actual authored route.
        entered_book: Whether the book's explicit or legacy entry rule was met.
        complete: Whether the supplied actual game replay is complete.
        entry_ply: Observed explicit position entry (zero for an entered start);
            None means legacy entry semantics or an unentered anchored book.
    """
    game_id: int | None
    game_identity: str
    provenance: BookProvenance
    user_color: str | None
    moves: tuple[OpeningMoveAssessment, ...]
    known_book_positions: tuple[BookPositionVisit, ...]
    initial_variation: VariationContext
    final_variation: VariationContext
    followed_variations: tuple[tuple[NamedVariation, ...], ...]
    in_book_moves: int
    out_of_book_moves: int
    moves_with_alternatives: int
    user_in_book_moves: int | None
    opponent_in_book_moves: int | None
    first_deviation_ply: int | None
    last_known_before_deviation: BookPositionVisit | None
    last_known_position: BookPositionVisit | None
    reentry_count: int
    max_consecutive_in_book_plies: int
    entered_book: bool
    complete: bool = True
    entry_ply: int | None = None

    @property
    def variation_context_complete(self):
        return self.initial_variation.complete and all(
            m.variation_after.complete for m in self.moves if m.after_position_id is not None)

    @property
    def meaningful_match(self):
        return self.entered_book

    @property
    def total_plies(self):
        return len(self.moves)

    @property
    def first_deviation(self):
        return self.moves[self.first_deviation_ply-1] if self.first_deviation_ply else None

    @property
    def final_named_variation(self):
        return self.final_variation.deepest_name

    def is_current(self, provenance, game_identity=None):
        return self.provenance==provenance and (game_identity is None or self.game_identity==game_identity)


@dataclass(frozen=True)
class OpeningQuery:
    entered_book: bool | None = True
    variation_name: str = ""
    deviation_relation: str | None = None
    include_ambiguous_variations: bool = False
    reentered_book: bool | None = None

    def __post_init__(self):
        if (self.entered_book is not None and type(self.entered_book) is not bool) or self.deviation_relation not in (None,'user','opponent'):
            raise ValueError("Invalid opening query.")
        if self.reentered_book is not None and type(self.reentered_book) is not bool:
            raise ValueError("Re-entry filter must be boolean or None.")
        if not isinstance(self.variation_name,str):raise ValueError("Variation name must be text.")


@dataclass(frozen=True)
class OpeningFailure:
    game_id: int
    reason: str


@dataclass(frozen=True)
class OpeningBatchResult:
    assessments: tuple[OpeningGameAssessment, ...]
    errors: tuple[OpeningFailure, ...]
    games_entered: int
    in_book_moves: int
    known_position_visits: int
    reentries: int


@dataclass(frozen=True)
class OpeningVariationDistribution:
    provenance: BookProvenance
    counts: tuple[tuple[str, int], ...]
    assessed_games: int
    meaningful_matches: int
    errors: tuple[OpeningFailure, ...]


@dataclass(frozen=True)
class OpeningDeviationResult:
    provenance: BookProvenance
    deviations: tuple[OpeningMoveAssessment, ...]
    assessed_games: int
    errors: tuple[OpeningFailure, ...]
