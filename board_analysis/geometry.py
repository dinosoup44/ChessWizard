"""Board coordinates and rays, independent of occupancy or tactic rules."""
import chess

ORTHOGONAL_DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL_DIRECTIONS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
DIRECTIONS = ORTHOGONAL_DIRECTIONS + DIAGONAL_DIRECTIONS


def direction(source: chess.Square, target: chess.Square) -> tuple[int, int] | None:
    """Unit file/rank step for distinct rank/file/diagonal-aligned squares."""
    dx = chess.square_file(target) - chess.square_file(source)
    dy = chess.square_rank(target) - chess.square_rank(source)
    if (dx == dy == 0) or (dx and dy and abs(dx) != abs(dy)):
        return None
    return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))


def ray_squares(source: chess.Square, step: tuple[int, int]) -> tuple[chess.Square, ...]:
    """Squares from the next square to the edge, nearest first; excludes source."""
    if step not in DIRECTIONS:
        raise ValueError("A ray requires a unit orthogonal or diagonal direction")
    dx, dy = step
    file, rank = chess.square_file(source) + dx, chess.square_rank(source) + dy
    squares = []
    while 0 <= file < 8 and 0 <= rank < 8:
        squares.append(chess.square(file, rank))
        file, rank = file + dx, rank + dy
    return tuple(squares)


def between_squares(source: chess.Square, target: chess.Square) -> tuple[chess.Square, ...]:
    """Strictly between aligned endpoints, ordered from source; empty otherwise."""
    step = direction(source, target)
    if step is None:
        return ()
    ray = ray_squares(source, step)
    return ray[:ray.index(target)]


def neighborhood(square: chess.Square, radius: int = 1) -> tuple[chess.Square, ...]:
    """Chebyshev neighborhood, excluding center, in square-index order."""
    if type(radius) is not int or radius < 0:
        raise ValueError("Radius must be a nonnegative integer")
    return tuple(s for s in chess.SQUARES if s != square and chess.square_distance(square, s) <= radius)
