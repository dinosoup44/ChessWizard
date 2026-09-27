"""Read-only game browser queries composed with reusable tactic eligibility."""
from tactic_query import TacticQuery


class GameReviewRepository:
    def __init__(self, connection):
        self.connection = connection
        self.tactics = TacticQuery(connection)

    def games(self, tactic_filter: str | None = None) -> list[dict]:
        """Read eligible games with owner context when the legacy schema provides it.

        Args:
            tactic_filter: Optional existing tactic visibility filter.

        Returns:
            Newest-first game dictionaries; absent legacy owner identity remains None.
        """
        owner = 'user_id' if any(r[1]=='user_id' for r in self.connection.execute('PRAGMA table_info(games)')) else 'NULL AS user_id' 
        cursor = self.connection.execute(
            f"SELECT game_id,{owner},source,source_game_id,white_username,black_username,user_color,result "
            "FROM games WHERE COALESCE(source,'')<>'dev' ORDER BY julianday(replace(substr(played_at,1,10),'.','-') || substr(played_at,11)) DESC, game_id DESC")
        games = [dict(zip((d[0] for d in cursor.description),row)) for row in cursor]
        if tactic_filter is None:
            return games
        selected = self.tactics.game_ids(tactic_filter)
        return [g for g in games if g["game_id"] in selected]

    def moves(self, game_id):
        cursor = self.connection.execute(
            "SELECT move_id,ply_number,move_number,color,san_played,uci_played,fen_before,fen_after "
            "FROM moves WHERE game_id=? ORDER BY ply_number,move_id",(game_id,))
        return [dict(zip((d[0] for d in cursor.description),row)) for row in cursor]
