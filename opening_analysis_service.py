"""Read-only selected-repertoire application service; no UI, engine or persistence calls."""
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from analysis_control import check_cancelled, cancellable_reads
import sqlite3
from move_quality_repository import MoveQualityRepository
from opening_accuracy_evidence import assess_opening_evidence
from opening_accuracy_settings import OpeningAccuracySettings
from opening_analysis import compose_opening_game
from opening_analysis_models import OpeningAnalysisExclusion, OpeningAnalysisResult, OpeningMatchingSet
from opening_analysis_repository import OpeningAnalysisRepository
from opening_analysis_settings import OpeningAnalysisSettings
from opening_analysis_statistics import summarize_opening_analysis
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_managed import ManagedOpeningIntelligenceService
from opening_intelligence_models import OpeningFailure, OpeningMatchPolicy, identity
from opening_intelligence_service import OpeningIntelligenceService
from opening_library_service import OpeningLibraryService
from opening_repertoire import RepertoireSide


@dataclass(frozen=True)
class OpeningAnalysisProgress:
    """Describe real read-only aggregation work without estimating completion.

    Args:
        phase: Current factual processing stage.
        completed: Games already examined in the matching stage.
        total: Games in the selected read snapshot.
    """
    phase: str
    completed: int = 0
    total: int = 0


class OpeningAnalysisService:
    """Build transient repertoire analysis using explicit side and existing evidence.

    Args:
        database_path: User game database, always opened read-only.
        library: Optional managed-library service for selected-book lookup.
        settings: Neutral aggregation policy.
        accuracy_settings: Existing opening-window and Move Quality contract.
        match_policy: Existing meaningful authored-entry policy.
    """
    def __init__(self, database_path: str | Path, library: OpeningLibraryService | None = None, *,
                 settings: OpeningAnalysisSettings = OpeningAnalysisSettings(),
                 accuracy_settings: OpeningAccuracySettings = OpeningAccuracySettings(),
                 match_policy: OpeningMatchPolicy = OpeningMatchPolicy()) -> None:
        """Bind services without reading games or changing data.

        Args:
            database_path: Existing game database.
            library: Optional managed-library catalog service.
            settings: Aggregation policy.
            accuracy_settings: Shared opening accuracy settings.
            match_policy: Existing authored-match settings.
        """
        self.path = Path(database_path).resolve()
        self.books = ManagedOpeningIntelligenceService(self.path, library, policy=match_policy)
        self.settings, self.accuracy_settings = settings, accuracy_settings
        self.match_policy = match_policy

    def analyze_opening_book(self, library_id: str, book_id: int, game_ids: Iterable[int] | None = None,
                             *, user_id: int | None = None, cancel: Event | None = None,
                       progress: Callable[[OpeningAnalysisProgress], None] | None = None) -> OpeningAnalysisResult:
        """Analyze a selected managed book against a user's explicit or default history.

        Args:
            library_id: Canonical managed library identifier.
            book_id: Stable library-local book ID.
            game_ids: Optional explicit scope; None selects that user's real history.
            user_id: Stored owner identity, required if the scope has multiple owners.
            cancel: Optional worker-owned cancellation event; no partial result is delivered.
            progress: Optional synchronous observer, called on the invoking worker thread.

        Returns:
            Transient match set, game facts and neutral aggregate summaries.

        Raises:
            ValueError: Side, ownership, scope or selected book is invalid.
            sqlite3.Error: A read snapshot cannot be opened.
            AnalysisCancelled: A caller cancelled this read-only computation.
        """
        return self.analyze_lookup(self.books.lookup_for_book(library_id, book_id), game_ids, user_id=user_id, cancel=cancel, progress=progress)

    def analyze_lookup(self, lookup: OpeningBookLookup, game_ids: Iterable[int] | None = None,
                       *, user_id: int | None = None, cancel: Event | None = None,
                       progress: Callable[[OpeningAnalysisProgress], None] | None = None) -> OpeningAnalysisResult:
        """Analyze a frozen book snapshot, including temporary validation libraries.

        Args:
            lookup: Explicitly configured book snapshot using the service match policy.
            game_ids: Optional deduplicated database-local scope.
            user_id: Stored owner identity; never guessed from a username/opening name.
            cancel: Optional worker-owned cancellation event; no partial result is delivered.
            progress: Optional synchronous observer, called on the invoking worker thread.

        Returns:
            Immutable analysis, with invalid games and exclusions reported separately.

        Raises:
            ValueError: Side is unspecified, policies differ, or scope/ownership is invalid.
            sqlite3.Error: Reading the game snapshot fails.
            AnalysisCancelled: A caller cancelled this read-only computation.
        """
        check_cancelled(cancel)
        side = lookup.snapshot.book.repertoire_side
        if side is None:
            raise ValueError('Set this book\'s repertoire side to White, Black or Both/reference before analysis.')
        if lookup.policy != self.match_policy:
            raise ValueError('Book lookup and analysis service must share the match policy.')
        facts = OpeningIntelligenceService(self.path, lookup)
        games, errors, excluded = [], [], []
        meaningful = 0
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db, cancellable_reads(db, cancel):
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            repository = OpeningAnalysisRepository(db)
            ids, owner = repository.scope(game_ids, user_id)
            quality = MoveQualityRepository(db, self.accuracy_settings.quality)
            if progress:
                progress(OpeningAnalysisProgress('Finding matching games', 0, len(ids)))
            for completed, game_id in enumerate(ids, 1):
                check_cancelled(cancel)
                try:
                    context = repository.context(game_id)
                    if context.source == 'dev' or context.user_id != owner:
                        excluded.append(OpeningAnalysisExclusion(game_id, 'outside_user_history'))
                        continue
                    assessment = facts.assess_game_in_snapshot(db, game_id)
                    meaningful += int(assessment.meaningful_match)
                    reason = ('no_meaningful_match' if not assessment.meaningful_match
                              else 'unknown_user_color' if context.user_color is None
                              else 'wrong_repertoire_side' if side != RepertoireSide.BOTH and side != context.user_color
                              else None)
                    if reason:
                        excluded.append(OpeningAnalysisExclusion(game_id, reason, assessment.meaningful_match))
                        continue
                    evidence = assess_opening_evidence(assessment, quality, lookup.policy,
                        self.accuracy_settings, include_user_deviations=True)
                    games.append(compose_opening_game(context, assessment, evidence, lookup))
                except (ValueError, KeyError, TypeError, sqlite3.Error) as error:
                    errors.append(OpeningFailure(game_id, str(error)))
                finally:
                    if progress:
                        progress(OpeningAnalysisProgress('Finding matches and reading stored evaluations', completed, len(ids)))
        check_cancelled(cancel)
        matching = OpeningMatchingSet(lookup.provenance, side, facts.namespace, owner, ids,
            tuple(game.context.game_id for game in games), meaningful, tuple(excluded), tuple(errors))
        policy = identity((asdict(self.settings), self.accuracy_settings.currentness_identity))
        if progress:
            progress(OpeningAnalysisProgress('Calculating statistics, deviations and opening gaps', len(ids), len(ids)))
        return summarize_opening_analysis(matching, tuple(games), self.settings, policy)
