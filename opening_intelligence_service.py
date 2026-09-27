"""Read-only stored-game batches and query hooks for Review, Explorer and lessons."""
from contextlib import closing
from collections import Counter
from pathlib import Path
import sqlite3
from game_review_repository import GameReviewRepository
from opening_intelligence_application import assess_game
from opening_intelligence_models import OpeningGameAssessment, OpeningQuery, OpeningFailure, OpeningBatchResult, identity


def matches_opening(assessment: OpeningGameAssessment, query: OpeningQuery = OpeningQuery()) -> bool:
    """Filter replay facts, including named entry reached by an alternate move order.

    Args:
        assessment: Complete authored-book replay.
        query: Optional entry, variation, departure and re-entry filters.

    Returns:
        Whether the factual replay satisfies every requested filter.
    """
    if query.entered_book is not None and assessment.entered_book!=query.entered_book:return False
    if query.reentered_book is not None and bool(assessment.reentry_count)!=query.reentered_book:return False
    if query.deviation_relation is not None and not any(m.deviation_relation==query.deviation_relation for m in assessment.moves):return False
    if query.variation_name:
        contexts=[m.variation_after for m in assessment.moves if m.played_move_in_book
                  or (assessment.entry_ply is not None and m.after_position_id is not None)]
        if not any(v.name==query.variation_name for c in contexts if query.include_ambiguous_variations or not c.ambiguous
                   for path in c.paths for v in path):return False
    return True


def variation_distribution(assessments):
    """Final known context distribution; ambiguity and unnamed trunks remain explicit."""
    return dict(Counter('Ambiguous' if a.final_variation.ambiguous else a.final_named_variation or 'Unnamed trunk'
                        for a in assessments if a.entered_book))


def get_deviations(assessments):
    return tuple(move for assessment in assessments for move in assessment.moves if move.deviation)


class OpeningIntelligenceService:
    def __init__(self,database_path,lookup):
        self.path=Path(database_path).resolve();self.lookup=lookup
        self.namespace=identity(str(self.path).casefold())

    def _connect(self):
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        return db

    def game_ids(self):
        """Explicit discovery of real-game scope; no assessment runs implicitly."""
        with closing(self._connect()) as db:
            return tuple(r[0] for r in db.execute("SELECT game_id FROM games WHERE COALESCE(source,'')<>'dev' ORDER BY game_id"))

    def assess_game_in_snapshot(self,db,game_id):
        """Assess using the caller-owned read transaction for coherent derived joins."""
        row=db.execute('SELECT user_color,variant,source,source_game_id FROM games WHERE game_id=?',(game_id,)).fetchone()
        if row is None:raise ValueError('Game not found in this database.')
        if row[1] and row[1].lower() not in ('standard','chess'):raise ValueError('Standard chess only.')
        moves=GameReviewRepository(db).moves(game_id)
        if not moves:raise ValueError('No stored moves; initial position is unknown.')
        return assess_game(self.lookup,(m['uci_played'] for m in moves),initial_fen=moves[0]['fen_before'],
            game_id=game_id,user_color=row[0],stored_moves=moves,game_namespace=identity((self.namespace,row[2],row[3])))

    def iter_games(self,game_ids):
        """Stream the explicit deduplicated scope in one consistent read transaction."""
        ids=tuple(dict.fromkeys(game_ids))
        if any(type(i) is not int or i<=0 for i in ids):raise ValueError('Use positive database-local game IDs.')
        with closing(self._connect()) as db:
            for game_id in ids:
                try:yield self.assess_game_in_snapshot(db,game_id)
                except (ValueError,KeyError,TypeError,sqlite3.Error) as error:yield OpeningFailure(game_id,str(error))

    def assess_game(self,game_id):
        value=next(self.iter_games((game_id,)))
        if isinstance(value,OpeningFailure):raise ValueError(value.reason)
        return value

    def assess_games(self,game_ids):
        values=tuple(self.iter_games(game_ids))
        assessments=tuple(v for v in values if not isinstance(v,OpeningFailure))
        errors=tuple(v for v in values if isinstance(v,OpeningFailure))
        return OpeningBatchResult(assessments,errors,sum(a.entered_book for a in assessments),
            sum(a.in_book_moves for a in assessments),sum(len(a.known_book_positions) for a in assessments),
            sum(a.reentry_count for a in assessments))

    def get_games_for_opening(self,game_ids,query=OpeningQuery()):
        """Filter only successful assessments; failures are returned separately."""
        result=self.assess_games(game_ids)
        selected=tuple(a for a in result.assessments if matches_opening(a,query))
        return OpeningBatchResult(selected,result.errors,len([a for a in selected if a.entered_book]),
            sum(a.in_book_moves for a in selected),sum(len(a.known_book_positions) for a in selected),sum(a.reentry_count for a in selected))
