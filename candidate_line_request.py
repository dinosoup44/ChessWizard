"""Engine request identity includes any explicit restriction to known root moves."""
from dataclasses import asdict
from analysis_settings import identity


def normalized_root_moves(root_moves):
    return tuple(sorted(set(root_moves)))


def request_identity(settings, root_moves=()):
    moves = normalized_root_moves(root_moves)
    if not moves:
        return identity(settings)
    return identity({'generator': asdict(settings), 'root_moves': moves})
