VALID_RESULTS = {
    "in_progress",
    "solved",
    "revealed",
    "quit",
}


def start_attempt(
    connection,
    candidate_id,
    tactic_type,
    episode_id=None
):
    """
    Create a new training attempt when a puzzle
    is presented to the user.

    candidate_id is the permanent anchor.

    episode_id is optional because some tactic
    types, such as our current fork detector,
    do not have episode grouping yet.
    """

    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO training_attempts (
            candidate_id,
            episode_id,
            tactic_type,
            result,
            move_attempts,
            wrong_move_attempts,
            hint_used,
            solution_revealed
        )
        VALUES (
            ?,
            ?,
            ?,
            'in_progress',
            0,
            0,
            0,
            0
        )
    """, (
        candidate_id,
        episode_id,
        tactic_type,
    ))

    connection.commit()

    return cursor.lastrowid


def record_move_attempt(
    connection,
    training_attempt_id,
    was_correct
):
    """
    Count one legal move submitted by the user.

    move_attempts:
        every legal move the user submits.

    wrong_move_attempts:
        only legal moves that were not part
        of Merlin's expected solution line.
    """

    cursor = connection.cursor()

    if was_correct:

        cursor.execute("""
            UPDATE training_attempts

            SET move_attempts =
                move_attempts + 1

            WHERE training_attempt_id = ?
              AND result = 'in_progress'
        """, (
            training_attempt_id,
        ))

    else:

        cursor.execute("""
            UPDATE training_attempts

            SET
                move_attempts =
                    move_attempts + 1,

                wrong_move_attempts =
                    wrong_move_attempts + 1

            WHERE training_attempt_id = ?
              AND result = 'in_progress'
        """, (
            training_attempt_id,
        ))

    connection.commit()


def mark_hint_used(
    connection,
    training_attempt_id
):
    """
    Mark that the user requested or displayed
    a hint during this puzzle.
    """

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE training_attempts

        SET hint_used = 1

        WHERE training_attempt_id = ?
          AND result = 'in_progress'
    """, (
        training_attempt_id,
    ))

    connection.commit()


def mark_solution_revealed(
    connection,
    training_attempt_id
):
    """
    Mark that the puzzle solution was exposed
    before the attempt finished.
    """

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE training_attempts

        SET solution_revealed = 1

        WHERE training_attempt_id = ?
          AND result = 'in_progress'
    """, (
        training_attempt_id,
    ))

    connection.commit()


def finish_attempt(
    connection,
    training_attempt_id,
    result
):
    """
    Finish an active attempt.

    Expected finished results are:

        solved
        revealed
        quit
    """

    if result not in VALID_RESULTS:
        raise ValueError(
            f"Invalid training result: "
            f"{result}"
        )

    if result == "in_progress":
        raise ValueError(
            "finish_attempt cannot finish "
            "an attempt as in_progress."
        )

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE training_attempts

        SET
            result = ?,
            finished_at =
                CURRENT_TIMESTAMP

        WHERE training_attempt_id = ?
          AND result = 'in_progress'
    """, (
        result,
        training_attempt_id,
    ))

    connection.commit()


def get_attempt(
    connection,
    training_attempt_id
):
    """
    Read one training attempt.

    Useful for the UI and for developer tests.
    """

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            training_attempt_id,
            candidate_id,
            episode_id,
            tactic_type,
            result,
            move_attempts,
            wrong_move_attempts,
            hint_used,
            solution_revealed,
            started_at,
            finished_at,
            created_at

        FROM training_attempts

        WHERE training_attempt_id = ?
    """, (
        training_attempt_id,
    ))

    row = cursor.fetchone()

    if row is None:
        return None

    return {
        "training_attempt_id":
            row[0],

        "candidate_id":
            row[1],

        "episode_id":
            row[2],

        "tactic_type":
            row[3],

        "result":
            row[4],

        "move_attempts":
            row[5],

        "wrong_move_attempts":
            row[6],

        "hint_used":
            bool(row[7]),

        "solution_revealed":
            bool(row[8]),

        "started_at":
            row[9],

        "finished_at":
            row[10],

        "created_at":
            row[11],
    }


def is_perfect_solve(
    attempt
):
    """
    A perfect solve means:

    - the puzzle was solved
    - no wrong legal moves
    - no hint used
    - solution was not revealed
    """

    if attempt is None:
        return False

    return (
        attempt["result"] == "solved"
        and attempt[
            "wrong_move_attempts"
        ] == 0
        and not attempt[
            "hint_used"
        ]
        and not attempt[
            "solution_revealed"
        ]
    )