import sqlite3
from typing import Any, Protocol
import time
import chess
import chess.engine


DB_NAME = "merlin.db"

STOCKFISH_PATH = (
    r"Engines\Stockfish\stockfish-windows-x86-64-avx2"
    r"\stockfish\stockfish-windows-x86-64-avx2.exe"
)

ENGINE_NAME = "Stockfish"
ENGINE_VERSION = "18"


PROFILES = {
    "tactic_scout_v1": {
        "analysis_version": 1,
        "limit_type": "nodes",
        "limit_value": 10000,
    },
    "tactic_quick_v1": {
        "analysis_version": 1,
        "limit_type": "depth",
        "limit_value": 10,
    },

    "tactic_verify_v1": {
        "analysis_version": 1,
        "limit_type": "depth",
        "limit_value": 18,
    },
}


def get_profile(profile_name):
    if profile_name not in PROFILES:
        raise ValueError(
            f"Unknown engine profile: "
            f"{profile_name}"
        )

    return PROFILES[
        profile_name
    ]


def get_cached_position(
    connection,
    fen,
    profile_name
):
    profile = get_profile(
        profile_name
    )

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            cache_id,
            fen,
            engine_name,
            engine_version,
            analysis_profile,
            analysis_version,
            limit_type,
            limit_value,
            side_to_move,
            score_type,
            score_cp,
            mate,
            best_move_uci,
            best_move_san,
            principal_variation,
            depth,
            seldepth,
            nodes,
            time_ms,
            analyzed_at,
            score_pov

        FROM engine_position_cache

        WHERE fen = ?
          AND engine_name = ?
          AND engine_version = ?
          AND analysis_profile = ?
          AND analysis_version = ?
          AND limit_type = ?
          AND limit_value = ?

        LIMIT 1
    """, (
        fen,
        ENGINE_NAME,
        ENGINE_VERSION,
        profile_name,
        profile["analysis_version"],
        profile["limit_type"],
        profile["limit_value"],
    ))

    row = cursor.fetchone()

    if row is None:
        return None

    (
        cache_id,
        fen,
        engine_name,
        engine_version,
        analysis_profile,
        analysis_version,
        limit_type,
        limit_value,
        side_to_move,
        score_type,
        score_cp,
        mate,
        best_move_uci,
        best_move_san,
        principal_variation,
        depth,
        seldepth,
        nodes,
        time_ms,
        analyzed_at,
        score_pov
    ) = row

    return {
        "cache_id": cache_id,

        "fen": fen,

        "engine_name":
            engine_name,

        "engine_version":
            engine_version,

        "analysis_profile":
            analysis_profile,

        "analysis_version":
            analysis_version,

        "limit_type":
            limit_type,

        "limit_value":
            limit_value,

        "side_to_move":
            side_to_move,

        "score_type":
            score_type,

        "score_cp":
            score_cp,

        "mate":
            mate,

        "best_move_uci":
            best_move_uci,

        "best_move_san":
            best_move_san,

        "principal_variation":
            principal_variation,

        "depth":
            depth,

        "seldepth":
            seldepth,

        "nodes":
            nodes,

        "time_ms":
            time_ms,

        "analyzed_at":
            analyzed_at,

        "score_pov":
            score_pov,

        "cache_hit":
            True,
    }


def build_pv_san(
    board,
    pv_moves
):
    """
    Convert Stockfish's PV moves into SAN while
    walking forward through a copy of the board.
    """

    pv_board = board.copy()

    san_moves = []

    for move in pv_moves:

        if move not in pv_board.legal_moves:
            break

        san = pv_board.san(
            move
        )

        san_moves.append(
            san
        )

        pv_board.push(
            move
        )

    return " ".join(
        san_moves
    )


class PositionEngine(Protocol):
    """Describe the shared engine surface required by the position cache."""

    def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs: Any) -> dict:
        """Request completed evidence from the caller-owned engine.

        Args:
            board: Position to analyze.
            limit: Unchanged engine search budget.
            **kwargs: Exact options/restrictions forwarded by the caller.

        Returns:
            Completed python-chess engine information.
        """
        ...


def analyze_position(
    connection: sqlite3.Connection,
    engine: PositionEngine,
    fen: str,
    profile_name: str
) -> dict:
    """Generate and persist exact position evidence under the current profile.

    Args:
        connection: Caller-owned cache connection; an outer transaction stays open.
        engine: Shared engine service exposing analyse.
        fen: Exact position identity.
        profile_name: Existing registered raw-engine profile.

    Returns:
        Completed White-POV cache evidence, including its stable cache ID.

    Raises:
        ValueError: The profile or position is unsupported.
        chess.engine.EngineError: The engine request failed.
        sqlite3.Error: Persistence failed; the outer stage must roll back.
    """
    profile = get_profile(
        profile_name
    )

    owns_transaction = not connection.in_transaction

    board = chess.Board(
        fen
    )

    if (
        profile["limit_type"]
        == "depth"
    ):
        limit = chess.engine.Limit(
            depth=profile[
                "limit_value"
            ]
        )

    elif profile["limit_type"] == "nodes":
        limit = chess.engine.Limit(nodes=profile["limit_value"])
    else:
        raise ValueError(
            "Unsupported engine limit type."
        )

    start_time = time.perf_counter()

    info = engine.analyse(
        board,
        limit
    )

    elapsed_ms = int(
        (
            time.perf_counter()
            - start_time
        )
        * 1000
    )

    # -------------------------------------------------
    # IMPORTANT:
    #
    # Cache EVERYTHING from White's point of view.
    #
    # Positive cp/mate = good for White.
    # Negative cp/mate = good for Black.
    # -------------------------------------------------

    score = info[
        "score"
    ].pov(
        chess.WHITE
    )

    mate_score = score.mate()

    if mate_score is not None:

        score_type = "mate"

        score_cp = None

        mate = mate_score

    else:

        score_type = "cp"

        mate = None

        score_cp = score.score()

    pv = info.get(
        "pv",
        []
    )

    best_move_uci = None
    best_move_san = None
    principal_variation = None

    if pv:

        best_move = pv[0]

        best_move_uci = (
            best_move.uci()
        )

        if best_move in board.legal_moves:

            best_move_san = (
                board.san(
                    best_move
                )
            )

        principal_variation = (
            build_pv_san(
                board,
                pv
            )
        )

    side_to_move = (
        "white"
        if board.turn == chess.WHITE
        else "black"
    )

    depth = info.get(
        "depth"
    )

    seldepth = info.get(
        "seldepth"
    )

    nodes = info.get(
        "nodes"
    )

    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO engine_position_cache (
            fen,
            engine_name,
            engine_version,
            analysis_profile,
            analysis_version,
            limit_type,
            limit_value,
            side_to_move,
            score_type,
            score_cp,
            mate,
            best_move_uci,
            best_move_san,
            principal_variation,
            depth,
            seldepth,
            nodes,
            time_ms,
            score_pov
        )

        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        fen,
        ENGINE_NAME,
        ENGINE_VERSION,
        profile_name,
        profile[
            "analysis_version"
        ],
        profile[
            "limit_type"
        ],
        profile[
            "limit_value"
        ],
        side_to_move,
        score_type,
        score_cp,
        mate,
        best_move_uci,
        best_move_san,
        principal_variation,
        depth,
        seldepth,
        nodes,
        elapsed_ms,
        "white",
    ))

    if owns_transaction:
        connection.commit()

    cache_id = (
        cursor.lastrowid
    )

    return {
        "cache_id": cache_id,

        "fen": fen,

        "engine_name":
            ENGINE_NAME,

        "engine_version":
            ENGINE_VERSION,

        "analysis_profile":
            profile_name,

        "analysis_version":
            profile[
                "analysis_version"
            ],

        "limit_type":
            profile[
                "limit_type"
            ],

        "limit_value":
            profile[
                "limit_value"
            ],

        "side_to_move":
            side_to_move,

        "score_type":
            score_type,

        "score_cp":
            score_cp,

        "mate":
            mate,

        "best_move_uci":
            best_move_uci,

        "best_move_san":
            best_move_san,

        "principal_variation":
            principal_variation,

        "depth":
            depth,

        "seldepth":
            seldepth,

        "nodes":
            nodes,

        "time_ms":
            elapsed_ms,

        "score_pov":
            "white",

        "cache_hit":
            False,
    }


def get_or_analyze(
    connection,
    engine,
    fen,
    profile_name
):
    """
    Main function future Merlin tools should use.

    Cache first.
    Stockfish only if needed.
    """

    cached = get_cached_position(
        connection,
        fen,
        profile_name
    )

    if cached is not None:
        return cached

    return analyze_position(
        connection,
        engine,
        fen,
        profile_name
    )


def score_for_color(
    result,
    color
):
    """
    Convert the cached WHITE-POV result into
    the requested player's POV.

    Returns:

        {
            "score_type": "cp" or "mate",
            "score_cp": ...,
            "mate": ...
        }
    """

    multiplier = (
        1
        if color == chess.WHITE
        else -1
    )

    if result[
        "score_type"
    ] == "mate":

        return {
            "score_type": "mate",

            "score_cp": None,

            "mate": (
                result["mate"]
                * multiplier
            ),
        }

    return {
        "score_type": "cp",

        "score_cp": (
            result["score_cp"]
            * multiplier
        ),

        "mate": None,
    }
