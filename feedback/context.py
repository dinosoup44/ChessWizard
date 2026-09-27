"""Pure normalization: opportunity > known legacy metadata > canonical fields."""
from dataclasses import replace
import json
from tactical_opportunities import opportunity_from_dict, ProofEvidence
from .adapters import default_adapters
from exchange_presentation import exchange_presentation_from_dict
from .models import FeedbackContext
from .opportunity_facts import target_payoff_facts


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


class FeedbackContextBuilder:
    def __init__(self, adapters=None):
        self.adapters = adapters or default_adapters()

    def build(self, candidate, opportunity=None):
        row = dict(candidate)
        warnings = []
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
            if not isinstance(metadata, dict):
                raise ValueError("Expected an object")
        except (ValueError, TypeError):
            metadata = {}
            warnings.append("Invalid optional metadata; canonical evidence retained.")
        document = metadata.get("tactical_opportunity")
        try:
            if opportunity is None and document is not None:
                opportunity = opportunity_from_dict(document)
            if opportunity is not None:
                canonical = {"played_move_uci": row.get("uci_played"),
                             "tactical_move_uci": row.get("solution_move_uci"),
                             "line_san": row.get("solution_line")}
                for key, value in canonical.items():
                    if value is not None and getattr(opportunity.proof, key) not in (None, value):
                        raise ValueError("Conflicting canonical proof")
                opportunity = replace(opportunity, proof=replace(opportunity.proof,
                    **{k: v for k, v in canonical.items() if v is not None}))
        except (ValueError, TypeError, KeyError, AttributeError):
            opportunity = None
            warnings.append("Invalid or conflicting opportunity; legacy/canonical evidence retained.")

        legacy = {k: v for k, v in metadata.items() if k != "tactical_opportunity"}
        color = row.get("color") or row.get("player_color")
        evidence = None
        if opportunity is None:
            try:
                evidence = self.adapters.build(row.get("tactic_type"), legacy, color)
            except (ValueError, TypeError, KeyError, AttributeError):
                from .adapters import LegacyEvidence
                evidence = LegacyEvidence()
                warnings.append("Invalid legacy evidence; canonical fields retained.")
        played = _text(row.get("san_played")) or _text(row.get("uci_played"))
        recommended = _text(row.get("solution_move_san")) or _text(row.get("solution_move_uci"))
        proof_line = _text(row.get("solution_line"))
        if proof_line is None and opportunity:
            proof_line = _text(opportunity.proof.line_san)
        if evidence:
            played = played or _text(evidence.played_move)
            recommended = recommended or _text(evidence.recommended_move)
            proof_line = proof_line or _text(evidence.proof_line)
        provenance = [("identity_moves", "canonical candidate + moves")]
        if opportunity:
            provenance.append(("outcome_motifs_proof_presentation", "metadata_json.tactical_opportunity"))
        if evidence:
            provenance.extend((fact.kind, source) for fact in evidence.facts for source in fact.sources)
            if evidence.proof:
                provenance.append(("numeric_evidence", "known legacy schema; explicit player perspective"))
        exchange = None
        if metadata.get("exchange_presentation") is not None:
            try:
                exchange = exchange_presentation_from_dict(metadata["exchange_presentation"],
                    row.get("fen_before"), proof_line or "")
            except (ValueError, TypeError, KeyError):
                warnings.append("Exchange detail is invalid or belongs to a different tactical line.")
        evaluation_delta = legacy.get("gain_vs_played_cp") if legacy.get("detector") == "fork_v2_post_conversion" else None
        if type(evaluation_delta) is not int: evaluation_delta = None
        return FeedbackContext(
            candidate_id=row.get("candidate_id"), move_id=row.get("move_id"), game_id=row.get("game_id"),
            player_color=row.get("color") or row.get("player_color"), move_number=row.get("move_number"),
            fen_before=row.get("fen_before"), played_move=played, recommended_move=recommended,
            tactic_type=row.get("tactic_type"),
            primary_outcome=opportunity.primary_outcome if opportunity else None,
            motifs=opportunity.motifs if opportunity else (),
            payoff_timing=str(opportunity.payoff_timing) if opportunity else None,
            proof=opportunity.proof if opportunity else (evidence.proof or ProofEvidence()), proof_line=proof_line,
            relationships=opportunity.relationships if opportunity else (),
            presentation_level=str(opportunity.presentation.level) if opportunity else None,
            confidence=row.get("confidence"), facts=target_payoff_facts(opportunity) if opportunity else evidence.facts,
            source_metadata_json=json.dumps({k: row[k] for k in ("source", "source_game_id", "detector_version", "episode_id") if k in row}, sort_keys=True),
            opportunity_metadata_json=json.dumps(opportunity.metadata, sort_keys=True) if opportunity else None,
            legacy_metadata_json=json.dumps(legacy, sort_keys=True) if legacy else None,
            notes=_text(row.get("notes")), provenance=tuple(provenance), warnings=tuple(warnings),
            exchange_presentation=exchange, recorded_evaluation_delta_cp=evaluation_delta)
