"""Fork-specific executable threats layered on unchanged geometric attack facts."""
from dataclasses import dataclass
import chess
from board_analysis import attacked_pieces

FUNCTIONAL_THREAT_VERSION = 1

@dataclass(frozen=True)
class ForkThreat:
    square: int
    piece_type: int
    executable: bool
    reason: str

@dataclass(frozen=True)
class FunctionalFork:
    threats: tuple[ForkThreat, ...]
    attacker_pinned: bool
    version: int = FUNCTIONAL_THREAT_VERSION

    @property
    def legal_targets(self):
        return tuple(t.square for t in self.threats if t.executable)

    @property
    def valid(self):
        return len(self.legal_targets) >= 2


def functional_fork_threats(board: chess.Board, move: chess.Move) -> FunctionalFork:
    """Test immediate target threats after a legal move, without predicting a reply.

    Non-king targets use a mover-turn legality probe on the resulting occupancy;
    it models a threat, never an actual opponent pass or a forced capture. Check
    counts as the king threat: kings are never captured. Later defense/payoff
    verification remains mandatory. Inputs and shared attack maps are unchanged.
    """
    if not board.is_valid() or not board.is_legal(move):
        raise ValueError('Functional Fork requires a valid position and legal move')
    player=board.turn
    after=board.copy(stack=False);after.push(move)
    probe=after.copy(stack=False);probe.turn=player;probe.ep_square=None
    threats=[]
    for target in attacked_pieces(after,move.to_square,target_color=not player,
            piece_types=(chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN,chess.KING)):
        if target.piece_type==chess.KING:
            executable=after.is_check()
            reason='check' if executable else 'not_a_legal_check'
        else:
            promotion=chess.QUEEN if after.piece_type_at(move.to_square)==chess.PAWN and chess.square_rank(target.square) in (0,7) else None
            executable=probe.is_legal(chess.Move(move.to_square,target.square,promotion=promotion))
            reason='legal_capture_threat' if executable else 'capture_exposes_own_king'
        threats.append(ForkThreat(target.square,target.piece_type,executable,reason))
    return FunctionalFork(tuple(threats),after.is_pinned(player,move.to_square))


def retain_functional_forks(board, proposals):
    """Retain legal target identities, not an all-or-nothing pinned-piece filter."""
    result=[]
    for proposal in proposals:
        facts=functional_fork_threats(board,board.parse_uci(proposal['move_uci']))
        if facts.valid:
            result.append({**proposal,'targets':[t for t in proposal['targets']
                if chess.parse_square(t['square']) in facts.legal_targets],
                'functional_threat_version':facts.version})
    return result
