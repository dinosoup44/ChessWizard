"""Portable exact occurrence projections for Opening Review drilldown."""
from dataclasses import dataclass
from opening_analysis_models import OpeningAnalysisGame, OpeningAnalysisResult
from opening_book_models import PositionIdentity
from opening_intelligence_models import OpeningMoveAssessment
from move_quality import MoveQuality


@dataclass(frozen=True)
class OpeningOccurrence:
    """Retain one actual visit, including repeated visits within the same game.

    Args:
        game: Matching game and its stored metrics.
        move: Exact actual decision, or None for a whole-game/variation entry.
        quality: Existing evaluation facts for the decision, when available.
    """
    game: OpeningAnalysisGame
    move: OpeningMoveAssessment | None = None
    quality: MoveQuality | None = None

    @property
    def key(self) -> str:
        """Identify this visit independently of table order.

        Returns:
            Game and one-based decision ply, with zero for whole-game entries.
        """
        return f'{self.game.context.game_id}:{self.move.ply if self.move else 0}'


def deviation_occurrences(result: OpeningAnalysisResult, position: PositionIdentity, move_uci: str,
                          party: str) -> tuple[OpeningOccurrence, ...]:
    """Resolve an aggregate departure to every exact actual visit.

    Args:
        result: Existing immutable aggregate; no data or engine requests are made.
        position: Canonical departure position from the aggregate row.
        move_uci: Actual departure move.
        party: Stored user/opponent relationship.

    Returns:
        Stable game/ply occurrences, preserving transpositions and repeated visits.
    """
    return tuple(OpeningOccurrence(game, row.book, row.quality)
                 for game in result.games for row in game.deviations
                 if row.book.position == position and row.book.played_uci == move_uci and row.party == party)


def variation_occurrences(result: OpeningAnalysisResult, game_ids: tuple[int, ...]) -> tuple[OpeningOccurrence, ...]:
    """Resolve a variation group using its existing matching membership.

    Args:
        result: Current immutable opening analysis.
        game_ids: Exact game identities carried by the variation summary.

    Returns:
        Matching games in the group's recorded order.
    """
    games = {game.context.game_id: game for game in result.games}
    return tuple(OpeningOccurrence(games[gid]) for gid in game_ids)


@dataclass(frozen=True)
class OpeningGameSelection:
    """Keep summary visits attached to one game without changing a board cursor.

    Args:
        game: Exact immutable game and opening facts.
        occurrences: Every visit belonging to the selected summary and game.
    """
    game: OpeningAnalysisGame
    occurrences: tuple[OpeningOccurrence, ...]

    @property
    def plies(self) -> tuple[int, ...] | None:
        """Return exact summary plies, or all moments for a whole-game selection.

        Returns:
            Ordered unique plies; None includes the whole game's moments.
        """
        if any(row.move is None for row in self.occurrences):
            return None
        return tuple(dict.fromkeys(row.move.ply for row in self.occurrences))


def affected_games(rows: tuple[OpeningOccurrence, ...]) -> tuple[OpeningGameSelection, ...]:
    """Group visits by game while retaining each exact occurrence below that row.

    Args:
        rows: Summary membership with exact opening/game/move provenance.

    Returns:
        One selectable row per game, in first-occurrence order.
    """
    grouped: dict[int, list[OpeningOccurrence]] = {}
    for row in rows:
        grouped.setdefault(row.game.context.game_id, []).append(row)
    return tuple(OpeningGameSelection(visits[0].game, tuple(visits)) for visits in grouped.values())
