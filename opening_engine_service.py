"""On-demand advisory engine requests using shared profiles, cancellation and exact caches."""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from time import perf_counter
import sqlite3
import chess
from analysis_control import check_cancelled
from analysis_engine import LazyScoutEngine
from analysis_settings import AnalysisProfile, load_profile
from application_paths import application_data_directory, application_root
from candidate_line_engine import CandidateLineGenerator
from candidate_line_repository import CandidateLineRepository
from candidate_line_request import request_identity
from candidate_line_service import CandidateLineService
from candidate_lines import CandidateLineSet
from migrate_candidate_line_cache import migrate, validate_schema
from opening_engine_models import OpeningEngineAnalysis, OpeningEngineAnchor


STUDIO_PROFILE_NAMES = ('quick', 'normal', 'deep')


def validate_opening_lines(value: CandidateLineSet, fen: str, profile: AnalysisProfile) -> None:
    """Require complete compatible advisory evidence, never fabricated missing ranks.

    Args:
        value: Shared candidate-line result, already legally replayed by its model.
        fen: Exact requested FEN including clocks.
        profile: Shared raw generation settings requested by the user.

    Raises:
        ValueError: Identity, score POV, search completion or budget is incompatible.
    """
    settings = profile.generator
    if (value.fen != fen or value.engine_identity != request_identity(settings)
            or value.analysis_profile != settings.engine.profile_id
            or value.requested_line_count != settings.candidate_line_count
            or value.generation_metadata.get('complete') is not True
            or tuple(value.generation_metadata.get('root_moves', ()))):
        raise ValueError('Stockfish returned incomplete or incompatible line evidence. Try analysis again.')
    board = chess.Board(fen)
    expected = 0 if board.is_game_over() else min(settings.candidate_line_count, board.legal_moves.count())
    if value.generated_line_count != expected:
        raise ValueError('Stockfish did not finish the requested candidate lines.')
    if any(line.score.score_pov != 'white' or line.analysis_version != settings.analysis_version
           or (settings.engine.depth is not None and line.depth < settings.engine.depth) for line in value.lines):
        raise ValueError('Stockfish lines have an incompatible score or unfinished depth.')


class _CompatibleStore:
    def __init__(self, repository: CandidateLineRepository, profile: AnalysisProfile) -> None:
        self.repository, self.profile = repository, profile

    def get(self, fen: str, identity: str) -> CandidateLineSet | None:
        """Treat malformed/incomplete existing rows as misses without repairing them."""
        try:
            value = self.repository.get(fen, identity)
            if value is not None:
                validate_opening_lines(value, fen, self.profile)
            return value
        except (ValueError, KeyError, TypeError):
            return None


class OpeningEngineService:
    """Run explicit requests; constructors, navigation and cache probes start no engine.

    Args:
        database_path: Optional existing game evidence database, always read-only.
        cache_path: Advisory cache destination, defaulting to writable user-data cache.
        engine_root: Existing application directory containing the approved Stockfish.
    """
    def __init__(self, database_path: str | Path | None = None, *, cache_path: str | Path | None = None,
                 engine_root: str | Path | None = None) -> None:
        """Bind paths without creating files or starting processes.

        Args:
            database_path: Optional existing raw evidence source.
            cache_path: Separate advisory cache or explicitly isolated test cache.
            engine_root: Application engine root.

        Raises:
            ValueError: The advisory write path aliases the production evidence source.
        """
        self.database_path = Path(database_path).resolve() if database_path else None
        self.cache_path = Path(cache_path).resolve() if cache_path else application_data_directory() / 'cache' / 'opening_lines.sqlite3'
        self.engine_root = Path(engine_root) if engine_root else application_root()
        if self.database_path == self.cache_path:
            raise ValueError('Opening advice must use a separate cache, not write the game database.')

    def analyze_opening_position(self, anchor: OpeningEngineAnchor, profile: str | AnalysisProfile = 'normal', *,
                                 refresh: bool = False, cancel: Event | None = None) -> OpeningEngineAnalysis:
        """Analyze one saved position only after an explicit caller request.

        Args:
            anchor: Saved route/position identity captured by the caller.
            profile: Existing Quick/Normal/Deep preset, or shared typed settings.
            refresh: Request fresh session evidence while retaining insert-once cache rows.
            cancel: Worker-owned Stop event; partial or cancelled results are never cached.

        Returns:
            Validated advice, request provenance and honest elapsed/cache/search counts.

        Raises:
            AnalysisCancelled: Stop or navigation cancelled the owned request.
            ValueError: Profile, anchor or returned evidence is invalid/incomplete.
            OSError: The existing engine or writable advisory storage is unavailable.
            sqlite3.Error: A cache operation fails; no book mutation occurs.
            chess.engine.EngineError: Stockfish failed.
        """
        check_cancelled(cancel)
        if isinstance(profile, str):
            if profile not in STUDIO_PROFILE_NAMES:
                raise ValueError('Choose Quick, Normal or Deep.')
            profile = load_profile(profile)
        if not isinstance(profile, AnalysisProfile):
            raise ValueError('Use the shared typed analysis profile.')
        board = chess.Board(anchor.fen)
        from opening_book_models import position_identity
        if not board.is_valid() or position_identity(board) != anchor.position:
            raise ValueError('Select a valid saved book position.')
        started = perf_counter()
        with ExitStack() as stack:
            stores = []
            if not refresh:
                for path in (self.database_path, self.cache_path):
                    if path is not None and path.is_file():
                        db = stack.enter_context(closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)))
                        db.execute('PRAGMA query_only=ON')
                        stores.append(_CompatibleStore(CandidateLineRepository(db), profile))
            engine = LazyScoutEngine(stack, self.engine_root, cancel)
            shared = CandidateLineService(CandidateLineGenerator(engine), read_stores=stores)
            lines = shared.candidate_lines(anchor.fen, profile.generator)
            check_cancelled(cancel)
            validate_opening_lines(lines, anchor.fen, profile)
            cache_hit = bool(shared.stats['cache_hits'])
        check_cancelled(cancel)
        inserts = 0 if cache_hit else self._store(lines, cancel)
        return OpeningEngineAnalysis(anchor, profile, lines, datetime.now(timezone.utc).isoformat(),
            cache_hit, shared.stats['engine_searches'], inserts, perf_counter() - started)

    def _store(self, lines: CandidateLineSet, cancel: Event | None) -> int:
        check_cancelled(cancel)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.cache_path, timeout=0.25)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                # Only a dedicated cache may be initialized; never migrate a user library/game DB.
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables - {'engine_candidate_line_cache'}:
                    raise ValueError('The advisory cache path contains unrelated user data.')
                migrate(db) if not tables else validate_schema(db)
                check_cancelled(cancel)
                inserted = CandidateLineRepository(db).put(lines)
                check_cancelled(cancel)
            return int(inserted)
