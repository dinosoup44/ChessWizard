"""Deterministic wording of supplied facts; no DB, chess engine, or network IO."""
from .models import FeedbackResult
from .registry import default_registry
from .templates import COMMON


def _piece(piece):
    return f"{piece.color} {piece.piece} on {piece.square}"


class FeedbackGenerator:
    def __init__(self, registry=None):
        self.registry = registry or default_registry()

    def generate(self, context, style="concise_review", pack_id="merlin_default"):
        p = self.registry.get(pack_id)
        options = p.style(style)
        c = context
        missing = p.render("missing")
        recommended, played = c.recommended_move or missing, c.played_move or missing
        outcome = p.label("outcome_labels", c.primary_outcome.kind) if c.primary_outcome and c.primary_outcome.kind != "unknown" else None
        title = outcome or (p.render("fallback_title", tactic=p.label("tactic_labels", c.tactic_type))
                            if c.tactic_type and c.primary_outcome is None and not c.motifs
                            else p.render("unknown_title"))
        supported = tuple(m for m in c.motifs if m.attribution in {"supported", "verified"})
        motif_labels = tuple(p.label("motif_labels", m.kind) for m in supported)
        context_labels = tuple(p.label("motif_labels", m.kind) for m in c.motifs if m.attribution == "context_only")
        if outcome:
            template = "outcome_" + c.primary_outcome.kind
            if c.recommended_move:
                main = p.render(template, recommended=recommended) if template in COMMON else p.render("outcome", recommended=recommended, outcome=outcome)
            else:
                main = p.render("outcome_only", outcome=outcome)
        elif c.recommended_move and c.played_move:
            main = p.render("fallback", recommended=recommended, played=played)
        elif c.recommended_move:
            main = p.render("recommendation_only", recommended=recommended)
        else:
            main = p.render("no_recommendation")
        facts = []
        for fact in c.facts:
            values = dict(fact.values)
            if fact.kind == "fork_targets":
                if c.recommended_move:
                    main = p.render(fact.kind, recommended=recommended, **values)
            elif fact.kind in {"conversion", "classification", "line_relationship", "geometric_targets", "realized_capture", "settled_payoff", "counterplay_status", "counterplay_material_range", "verification_status"}:
                facts.append(p.render(fact.kind, **values))
            elif options["include_evidence"] and fact.kind in {"evaluation_cp", "evaluation_mate"}:
                facts.append(p.render(fact.kind, **values))
        # Only an explicitly supported/verified primary motif may supply the main
        # causal explanation. Unknown/context-only rationale is never rendered.
        primary = next((m for m in supported if m.primary), None)
        if c.proof_line and c.primary_outcome is not None:
            tokens = c.proof_line.split()
            preview = " → ".join(tokens[:5]) + (" …" if len(tokens) > 5 else "")
            facts.insert(0, p.render("continuation", line=preview))
        elif primary and primary.rationale:
            facts.insert(0, primary.rationale)
        explanation = " ".join([main, *facts])
        exchange_summary = None
        exchange_continuation = None
        if c.exchange_presentation and options["summary_template"] == "explanation":
            detail = c.exchange_presentation
            exchange_continuation = detail.continuation_line or None
            if detail.settled_material_cp is None:
                exchange_summary = p.render("exchange_incomplete", reason=detail.reason.replace("_", " "))
            elif detail.settled_material_cp == 0:
                exchange_summary = p.render("exchange_balanced", pov=detail.player_color)
            else:
                exchange_summary = p.render("exchange_material", value=f"{detail.settled_material_cp:+d}", pov=detail.player_color)
            parts = [p.render("exchange_short", line=detail.short_line)]
            if exchange_continuation:
                parts.append(p.render("exchange_line", state=detail.state, line=exchange_continuation))
            parts.append(exchange_summary)
            if c.recorded_evaluation_delta_cp is not None:
                parts.append(p.render("exchange_evaluation", value=f"{c.recorded_evaluation_delta_cp:+d}"))
            explanation += "\n\n" + "\n".join(parts)
        teaching_note = None
        if options["include_evidence"]:
            details = self._evidence(c, p)
            if details:
                explanation += "\n\n" + "\n".join(details)
        if options["include_teaching_note"]:
            teaching_note = p.render("teaching_note")
        location = p.render("location", number=str(c.move_number), color=f" {c.player_color.capitalize()}" if c.player_color else "") if c.move_number is not None else ""
        mode = options["summary_template"]
        short = explanation.split("\n\n")[0] if mode == "explanation" else p.render(mode, title=title, location=location, recommended=recommended, played=played)
        if mode in {"alert", "summary"}:
            explanation = short
        return FeedbackResult(
            title=title, short_summary=short, explanation=explanation, outcome_label=outcome,
            motif_labels=motif_labels, context_motif_labels=context_labels,
            played_move_label=p.render("played", move=played), recommended_move_label=p.render("recommended", move=recommended),
            proof_summary=p.render("proof", line=c.proof_line) if c.proof_line else None,
            presentation_level=c.presentation_level or "unknown", detail_level=options["detail_level"],
            teaching_note=teaching_note, warning_note=" ".join(c.warnings) or None,
            provenance=(*c.provenance, ("pack", pack_id), ("style", style)),
            attribution_labels=tuple(p.render("attribution", motif=p.label("motif_labels", m.kind), attribution=str(m.attribution).replace("_", " ")) for m in c.motifs),
            relationship_labels=tuple(self._relationships(c, p)), proof_line=c.proof_line,
            exchange_continuation=exchange_continuation, exchange_summary=exchange_summary)

    @staticmethod
    def _relationships(c, p):
        details = []
        for line in c.relationships:
            values = dict(relationship=line.relationship_type.replace("_", " "), attacker=_piece(line.attacker), rear=_piece(line.rear_target))
            if line.intervening_piece:
                details.append(p.render("line_relationship", front=_piece(line.intervening_piece), **values))
            else:
                details.append(p.render("line_endpoint", **values))
        return details

    @staticmethod
    def _evidence(c, p):
        details = FeedbackGenerator._relationships(c, p)
        if c.payoff_timing and c.payoff_timing != "unknown":
            details.append(p.render("timing", timing=c.payoff_timing))
        proof = c.proof
        if proof.score_pov != "unknown":
            if proof.retained_material_gain_cp is not None:
                details.append(p.render("material", value=str(proof.retained_material_gain_cp), pov=proof.score_pov))
            for field, stage in (("evaluation_after_played", "after-played"), ("evaluation_after_tactic", "after-tactic"), ("evaluation_after_settlement", "after-settlement")):
                evaluation = getattr(proof, field)
                if evaluation:
                    for kind in ("cp", "mate"):
                        value = getattr(evaluation, kind)
                        if value is not None:
                            details.append(p.render("evaluation_" + kind, stage=stage, value=str(value), pov=proof.score_pov))
        return details
