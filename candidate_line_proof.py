"""Bridge approved line sets to the existing bounded-proof callback contract."""
from analysis_settings import AnalysisProfile
from quality_gate import approve_lines
from proof_evidence_state import terminal_facts
import chess


from evidence_errors import IncompleteLineEvidence


class TerminalPositionEvidence(ValueError):
    """Complete terminal evidence has no best continuation to select."""
    def __init__(self, fen):
        self.facts = terminal_facts(chess.Board(fen))
        super().__init__(self.facts.terminal_state)


class ApprovedPositionEvidence:
    """Every selected move passed the shared gate or is explicitly critical fallback."""

    def __init__(self, line_service, profile=AnalysisProfile()):
        self.line_service = line_service
        self.profile = profile
        self.positions = {}
        self.critical_positions = set()

    def approved(self, fen):
        if fen not in self.positions:
            raw = self.line_service.candidate_lines(fen, self.profile.generator)
            self.positions[fen] = approve_lines(raw, self.profile.quality_gate,
                                                expected_engine_identity=self.profile.engine_identity)
        result = self.positions[fen]
        if result.state == 'incomplete':
            raise IncompleteLineEvidence(result.decisions[0].reason if result.decisions else 'missing_lines')
        if result.forced_deterioration:
            self.critical_positions.add(fen)
        return result

    def best(self, fen):
        result = self.approved(fen)
        if result.state == 'terminal':
            raise TerminalPositionEvidence(fen)
        if not result.lines:
            raise IncompleteLineEvidence('No nonterminal approved line')
        return result.lines[0]

    def raw(self, fen, selected=None):
        approved = self.approved(fen)
        line = selected if selected is not None else self.best(fen)
        if line not in approved.lines:
            raise ValueError('Proof cannot select a Quality-Gate-rejected move')
        score = line.score.pov('white')
        return {'score_pov': 'white', 'score_type': 'cp' if score.score_cp is not None else 'mate',
                'score_cp': score.score_cp, 'mate': score.mate_score,
                'principal_variation': ' '.join(line.pv_san), 'best_move_uci': line.move_uci,
                'best_move_san': line.move_san, 'profile': self.profile.profile_id}
