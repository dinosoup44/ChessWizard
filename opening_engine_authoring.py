"""Explicit advisory-to-authoring boundary; no engine request or implicit book edits."""
import json
from candidate_lines import to_data
from opening_book_line import BookLinePlan, plan_book_line
from opening_book_repository import OpeningBookRepository
from opening_engine_models import OpeningEngineAnalysis, OpeningEngineAnchor, saved_opening_anchor
from opening_engine_service import validate_opening_lines

STALE_ANCHOR_MESSAGE = ('This analysis belongs to a different book position or revision. '
                        'Return to that position or analyze again.')


class OpeningEngineAuthoringService:
    """Prepare and commit confirmed engine lines through the normal book repository.

    Args:
        repository: Explicit authoring repository; never acquired by the engine layer.
        library_identity: Canonical target library namespace.
    """
    def __init__(self, repository: OpeningBookRepository, library_identity: str) -> None:
        """Bind the destination without writing.

        Args:
            repository: Caller-owned authoring repository.
            library_identity: Stable destination library identity.
        """
        self.repository, self.library_identity = repository, library_identity

    def preview_add(self, analysis: OpeningEngineAnalysis, rank: int, current_anchor: OpeningEngineAnchor,
                    *, variation_name: str = '') -> BookLinePlan:
        """Prepare an exact-position, whole-line confirmation without changing a book.

        Args:
            analysis: Completed advisory result.
            rank: Actual returned candidate rank.
            current_anchor: Currently selected saved route, independently supplied by the frontend.
            variation_name: Optional author-chosen name for the first new edge.

        Returns:
            Additive merge plan with legal SAN and existing/new edge counts.

        Raises:
            ValueError: Selection, revision, rank or evidence no longer matches.
            ReadOnlyLibraryError: The caller selected external read-only content.
        """
        self.repository.require_writable()
        if analysis.anchor != current_anchor or current_anchor.library_identity != self.library_identity:
            raise ValueError(STALE_ANCHOR_MESSAGE)
        snapshot = self.repository.snapshot(current_anchor.book_id)
        fresh = saved_opening_anchor(snapshot, self.library_identity, current_anchor.path)
        if fresh != current_anchor:
            raise ValueError(STALE_ANCHOR_MESSAGE)
        validate_opening_lines(analysis.lines, current_anchor.fen, analysis.profile)
        line = next((line for line in analysis.lines.lines if line.rank == rank), None)
        if line is None:
            raise ValueError('Select a returned Stockfish line.')
        engine = analysis.profile.generator.engine
        provenance = json.dumps({'authoring_engine': dict(engine=engine.engine_name, version=engine.engine_version,
            profile=analysis.profile.profile_id, requested_at=analysis.analyzed_at,
            request_identity=analysis.lines.engine_identity, root_position=current_anchor.position.canonical_fen,
            evaluation=to_data(line.score))}, sort_keys=True, separators=(',', ':'))
        return plan_book_line(snapshot, current_anchor.position_id, current_anchor.fen, line.pv_uci,
                              variation_name=variation_name, provenance_json=provenance)

    def add_engine_line_to_book(self, analysis: OpeningEngineAnalysis, rank: int, current_anchor: OpeningEngineAnchor,
                                confirmed_plan: BookLinePlan) -> tuple[int, ...]:
        """Apply only the exact reviewed plan to the still-selected saved anchor.

        Args:
            analysis: Completed advisory evidence shown during confirmation.
            rank: Selected actual candidate rank.
            current_anchor: Fresh frontend selection, never the preview board position.
            confirmed_plan: Plan explicitly approved by the author.

        Returns:
            Stable IDs for every selected-line move, preserving existing content.

        Raises:
            ValueError: Anchor, evidence or book changed since confirmation.
            sqlite3.Error: Persistence fails; the full line rolls back.
        """
        expected = self.preview_add(analysis, rank, current_anchor,
                                    variation_name=confirmed_plan.variation_name)
        if expected != confirmed_plan:
            raise ValueError('The book changed. Review a fresh Add as Variation preview.')
        return self.repository.apply_line(confirmed_plan)
