"""Report-only played Fork facts composed from shared legal board/range evidence."""
from dataclasses import dataclass
from typing import Literal
import chess
from board_analysis import attacked_pieces
from position_range_evidence import LegalReplay, PieceIdentity, CaptureEvent, MaterialTransition, TerminalState
from tactic_occurrences import TacticOccurrence, TacticColor, OccurrenceKind
from played_fork_proof import ForkPayoffEvidence

# Matches the existing Fork provider's target scope; attack maps do not imply legal captures.
FORK_TARGET_TYPES = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING)
GEOMETRY_SCOPE = 'moved_piece_geometric_attacks_enemy_non_pawns_v1'


@dataclass(frozen=True)
class ForkGeometry:
    status: Literal['confirmed_fork', 'not_fork', 'unresolved']
    attacker: PieceIdentity
    origin_square: int
    destination_square: int
    piece_type: int
    targets: tuple[PieceIdentity, ...]
    scope: str = GEOMETRY_SCOPE

    @property
    def target_count(self) -> int:
        return len(self.targets)


@dataclass(frozen=True)
class RecordedTargetCapture:
    """Victim identity is anchored before the root, even when the target later moves."""
    capture: CaptureEvent
    move_san: str
    by_forking_piece: bool

    @property
    def plies_after_root(self) -> int:
        return self.capture.ply - 1


@dataclass(frozen=True)
class RecordedForkConsequence:
    actual_line: tuple[str, ...]
    line_san: tuple[str, ...]
    target_captures: tuple[RecordedTargetCapture, ...]
    material: MaterialTransition | None
    gained_cp: int | None
    lost_cp: int | None
    net_cp: int | None
    status: Literal['positive_material_gain', 'neutral', 'material_loss', 'unresolved']
    completeness: str
    terminal: TerminalState | None

    @property
    def recorded_target_capture(self) -> bool | None:
        if self.completeness != 'supplied_recorded_window':
            return None
        return bool(self.target_captures)


@dataclass(frozen=True)
class PlayedForkAssessment:
    """Independent facts, not a master verified flag or a production tactic grade."""
    occurrence_identity: str
    actor_color: TacticColor
    perspective_color: TacticColor
    decision_fen: str
    actual_move: str
    actual_move_san: str
    geometry: ForkGeometry
    proof: ForkPayoffEvidence
    recorded: RecordedForkConsequence
    occurrence: TacticOccurrence | None
    review_readiness: Literal['ready_for_geometry_review', 'ready_for_recorded_consequence_review', 'insufficient_evidence']
    evidence_limitations: tuple[str, ...]
    provenance: tuple[tuple[str, str], ...]


def assess_played_fork(*, occurrence_identity: str, decision_fen: str, actual_move: str,
                      actor_color: TacticColor, perspective_color: TacticColor,
                      actual_line: tuple[str, ...] | None = None,
                      proof: ForkPayoffEvidence | None = None,
                      provenance: tuple[tuple[str, str], ...] = ()) -> PlayedForkAssessment:
    """Assess supplied moves only; invalid identities/legality fail rather than inventing evidence.

    A missing continuation leaves recorded consequence unresolved. Actual lines include
    the root. Material gained/lost includes promotions and is not causal Fork credit.
    """
    if not isinstance(provenance, tuple) or any(not isinstance(pair, tuple) or len(pair) != 2 or not all(isinstance(v, str) for v in pair) for pair in provenance):
        raise ValueError('Provenance must be immutable text pairs')
    if not occurrence_identity.strip():
        raise ValueError('Occurrence identity is required')
    actor, perspective = TacticColor(actor_color), TacticColor(perspective_color)
    root = LegalReplay(decision_fen, (actual_move,))
    board, after = root.board_at(0), root.board_at(1)
    if board.turn != (actor == TacticColor.WHITE):
        raise ValueError('Actor must match the source side to move')
    if actual_line is not None and (not isinstance(actual_line, tuple) or not actual_line or actual_line[0] != actual_move):
        raise ValueError('Actual line must be an immutable tuple starting with the recorded root')
    event = root.events[0]
    targets = tuple(root.identity_at_start(t.square) for t in attacked_pieces(after, event.to_square,
        target_color=not board.turn, piece_types=FORK_TARGET_TYPES))
    geometry = ForkGeometry('confirmed_fork' if len(targets) >= 2 else 'not_fork', event.actor,
        event.from_square, event.to_square, after.piece_type_at(event.to_square), targets)
    proof = proof or ForkPayoffEvidence(decision_fen, actual_move, occurrence_identity + ':proof_unavailable')
    if proof.decision_fen != decision_fen or proof.actual_move != actual_move:
        raise ValueError('Proof belongs to a different source position/move')
    recorded = _recorded_consequence(decision_fen, actual_line, geometry, board.turn)
    occurrence = None
    if geometry.status == 'confirmed_fork':
        # A geometry event does not claim verified payoff. All proof branches remain in the assessment.
        occurrence = TacticOccurrence('fork', occurrence_identity, kind=OccurrenceKind.PLAYED,
            actor_color=actor, perspective_color=perspective, source_position=decision_fen,
            actual_move=actual_move, tactical_move=actual_move, actual_game_line=actual_line or (actual_move,),
            source_verdict='confirmed_fork_geometry', provenance=(('geometry_scope', GEOMETRY_SCOPE),))
    readiness = ('insufficient_evidence' if geometry.status != 'confirmed_fork' else
                 'ready_for_recorded_consequence_review' if recorded.completeness == 'supplied_recorded_window' else
                 'ready_for_geometry_review')
    limitations = ('Geometry is an attack-map fact, not a guarantee of legal target capture or move quality.',
                  'Recorded material is bounded to the supplied line; it is not forced payoff or causal Fork credit.',
                  'Proof conclusions apply only to the supplied provider evidence and sampled scope.')
    if recorded.completeness != 'supplied_recorded_window':
        limitations += ('No recorded opponent response supplied; consequence is unresolved.',)
    return PlayedForkAssessment(occurrence_identity, actor, perspective, decision_fen, actual_move,
        event.san, geometry, proof, recorded, occurrence, readiness, limitations, provenance)


def _recorded_consequence(fen, line, geometry, actor):
    if line is None:
        return RecordedForkConsequence((), (), (), None, None, None, None, 'unresolved', 'unavailable', None)
    replay = LegalReplay(fen, line)
    evidence = replay.evidence(material_snapshots=True)
    material = evidence.material_transition
    captures = tuple(RecordedTargetCapture(e.capture, e.san, e.capture.capturer == geometry.attacker)
        for e in replay.events if e.capture and e.capture.victim in geometry.targets)
    gained = material.captured_by_side.for_color(actor) + material.promotion_delta.for_color(actor)
    lost = material.lost_by_side.for_color(actor) + material.promotion_delta.for_color(not actor)
    net = material.delta.for_color(actor) - material.delta.for_color(not actor)
    if gained - lost != net:
        raise ValueError('Toolkit material totals disagree')
    complete = len(line) > 1
    status = 'unresolved' if not complete else 'positive_material_gain' if net > 0 else 'material_loss' if net < 0 else 'neutral'
    return RecordedForkConsequence(line, tuple(e.san for e in replay.events), captures, material,
        gained, lost, net, status, 'supplied_recorded_window' if complete else 'root_only', evidence.terminal_state)
