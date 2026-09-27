# Import Games

Use **File > Import Games** with a Chess.com or Lichess username. Games are downloaded
and stored without starting analysis. For recent-game usefulness, then open **Analyze
Games > Recent 50**; full history is a separate explicit scope.

The summary separates new, duplicate, ignored, failed and **Skipped empty/zero-move**
records. A game with zero legal registered moves is skipped before normal insertion.
A valid one-move game is kept. Re-import preserves provider-identity deduplication.
Existing empty rows are excluded from analysis but are not silently deleted.

The maintained architecture, import/re-import, rollback and provider contract is in
[GAME_IMPORT.md](GAME_IMPORT.md). The related analysis-side behavior is documented
under [progressive batching and recoverable failures](ANALYZE_GAMES.md#progressive-batching-and-recoverable-failures).
