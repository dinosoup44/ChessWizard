"""Read-only SQL metadata filtering and shared stored-fact enrichment."""
from game_collection_schema import available as collections_available, MIGRATION_REQUIRED
from game_search_models import GameSearchCriteria, GameSearchResult, GameSearchRow
from game_search_tactics import GameSearchTactics, OccurrenceEvidenceSelection
from move_quality_repository import MoveQualityRepository

DATE_SQL = "julianday(replace(substr(g.played_at,1,10),'.','-') || substr(g.played_at,11))"
MOVES_SQL = "(SELECT (COUNT(*)+1)/2 FROM moves m WHERE m.game_id=g.game_id)"
OPPONENT_SQL = "CASE g.user_color WHEN 'white' THEN g.black_username WHEN 'black' THEN g.white_username END"
RESULT_SQL = """CASE WHEN g.result='1/2-1/2' THEN 'draw'
 WHEN g.user_color IN ('white','black') THEN CASE
 WHEN (g.result='1-0' AND g.user_color='white') OR (g.result='0-1' AND g.user_color='black') THEN 'win'
 WHEN g.result IN ('1-0','0-1') THEN 'loss' END END"""


def metadata_query(criteria):
    """Parameterized groups combine with AND; literal substring input is not SQL LIKE."""
    clauses, params = ["COALESCE(g.source,'')<>'dev'"], []
    for expression, value in (("g.game_id", criteria.game_id), ("g.user_color", criteria.color),
                              (RESULT_SQL, criteria.result), ("g.source", criteria.source),
                              ("g.time_control", criteria.time_control)):
        if value is not None and value != "":
            clauses.append(f"({expression})=?")
            params.append(value)
    for expression, value in ((OPPONENT_SQL, criteria.opponent), ("g.source_game_id", criteria.source_game_id)):
        if value:
            clauses.append(f"instr(lower(COALESCE(({expression}),'')),lower(?))>0")
            params.append(value)
    for operator, value in ((">=", criteria.date_from), ("<", criteria.date_to)):
        if value:
            clauses.append(f"{DATE_SQL}{operator}julianday(?){'+1' if operator == '<' else ''}")
            params.append(value)
    for operator, value in ((">=", criteria.min_moves), ("<=", criteria.max_moves)):
        if value is not None:
            clauses.append(f"{MOVES_SQL}{operator}?")
            params.append(value)
    if criteria.collection_id is not None:
        clauses.append("g.game_id IN (SELECT game_id FROM game_collection_members WHERE collection_id=?)")
        params.append(criteria.collection_id)
    elif criteria.uncollected:
        clauses.append("NOT EXISTS (SELECT 1 FROM game_collection_members cm WHERE cm.game_id=g.game_id)")
    return ("SELECT g.game_id,g.played_at,g.white_username,g.black_username,g.user_color,g.result,"
            f"g.source,g.source_game_id,g.time_control,{MOVES_SQL} AS move_count FROM games g WHERE "
            + " AND ".join(clauses) + f" ORDER BY {DATE_SQL} DESC,g.game_id DESC"), params


class GameSearchRepository:
    def __init__(self, connection, *, occurrence_selection=OccurrenceEvidenceSelection()):
        self.connection = connection
        self.tactics = GameSearchTactics(connection, occurrence_selection)
        self.quality = MoveQualityRepository(connection)

    def options(self):
        return {column: tuple(row[0] for row in self.connection.execute(
            f"SELECT DISTINCT {column} FROM games WHERE COALESCE(source,'')<>'dev' "
            f"AND {column} IS NOT NULL AND trim({column})<>'' ORDER BY {column}"))
            for column in ("source", "time_control")}

    def _accuracy_ready_games(self, games):
        """Bulk prefilter by exact raw roots; full shared validation still follows."""
        if not games or not self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='engine_candidate_line_cache'").fetchone():
            return set()
        placeholders = ",".join("?" for _ in games)
        return {row[0] for row in self.connection.execute(
            f"SELECT g.game_id FROM games g WHERE g.game_id IN ({placeholders}) "
            "AND g.user_color IN ('white','black') AND NOT EXISTS "
            "(SELECT 1 FROM moves m WHERE m.game_id=g.game_id AND m.color=g.user_color AND NOT EXISTS "
            "(SELECT 1 FROM engine_candidate_line_cache c WHERE c.fen=m.fen_before AND c.engine_identity=?))",
            (*[game['game_id'] for game in games], self.quality.settings.raw_identity))}

    def _accuracy(self, game):
        """Only complete user metrics qualify; no scoring policy is duplicated here."""
        try:
            quality = self.quality.game(game["game_id"], game["user_color"]).user
            return quality.accuracy if quality.complete else None
        except (ValueError, KeyError, TypeError):
            return None

    def search(self, criteria=GameSearchCriteria()):
        if (criteria.collection_id is not None or criteria.uncollected) and not collections_available(self.connection):
            raise ValueError(MIGRATION_REQUIRED)
        cursor = self.connection.execute(*metadata_query(criteria))
        columns = [d[0] for d in cursor.description]
        games = [dict(zip(columns, row)) for row in cursor]
        facts = self.tactics.facts(games)
        ready = self._accuracy_ready_games(games)
        rows = []
        for game in games:
            claims = facts[game["game_id"]]
            if (criteria.motifs or criteria.relationships) and not any(
                (not criteria.motifs or motif in criteria.motifs) and
                (not criteria.relationships or relation in criteria.relationships)
                for motif, relation in claims):
                continue
            accuracy = self._accuracy(game) if game["game_id"] in ready else None
            if criteria.min_accuracy is not None or criteria.max_accuracy is not None:
                if accuracy is None or (criteria.min_accuracy is not None and accuracy < criteria.min_accuracy) or (
                        criteria.max_accuracy is not None and accuracy > criteria.max_accuracy):
                    continue
            rows.append(GameSearchRow(game["game_id"], game["played_at"], game["white_username"],
                game["black_username"], game["user_color"], game["result"], game["move_count"],
                game["source"], game["source_game_id"], game["time_control"], accuracy, len(claims)))
        total = self.connection.execute("SELECT COUNT(*) FROM games WHERE COALESCE(source,'')<>'dev'").fetchone()[0]
        return GameSearchResult(tuple(rows), total, criteria)

