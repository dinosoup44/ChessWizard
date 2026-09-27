"""Built-in wording data. Fact selection belongs to generator/adapters."""
OUTCOME_LABELS = {
    "win_queen": "Win the queen", "win_rook": "Win the rook", "win_piece": "Win a piece",
    "win_pawn": "Win a pawn", "win_exchange": "Win the exchange",
    "force_favorable_exchange": "Force a favorable exchange",
}
MOTIF_LABELS = {"xray": "X-ray"}
TACTIC_LABELS = {"missed_xray": "X-ray"}

COMMON = {
    "fallback_title": "Missed {tactic}",
    "unknown_title": "Stored opportunity",
    "missing": "Not recorded",
    "played": "You played: {move}",
    "recommended": "Merlin found: {move}",
    "fallback": "The stored recommendation is {recommended}; you played {played}.",
    "recommendation_only": "The stored recommendation is {recommended}.",
    "no_recommendation": "No recommended move is recorded.",
    "outcome": "Recorded outcome for {recommended}: {outcome}.",
    "outcome_win_queen": "{recommended} wins the queen in the stored line.",
    "outcome_win_rook": "{recommended} wins the rook in the stored line.",
    "outcome_win_piece": "{recommended} wins a piece in the stored line.",
    "outcome_win_pawn": "{recommended} wins a pawn in the stored line.",
    "outcome_win_exchange": "{recommended} wins the exchange in the stored line.",
    "outcome_force_favorable_exchange": "{recommended} forces a favorable exchange in the stored line.",
    "outcome_only": "Recorded outcome: {outcome}.",
    "fork_targets": "{recommended} forks the {targets}.",
    "conversion": "In the stored line, {reply} is answered by {capture}, capturing the {target}.",
    "classification": "Stored outcome classification: {classification}.",
    "geometric_targets": "Attacked pieces: {targets}.",
    "realized_capture": "In the verified continuation, {move} captures the {target}.",
    "settled_payoff": "After settlement: net material change {change} cp; material balance {balance} cp ({pov} perspective).",
    "counterplay_status": "Counterplay review: {status}; {settled} of {count} sampled continuations settled.",
    "counterplay_material_range": "In the settled sampled branches, net material change ranges from {minimum} to {maximum} cp.",
    "verification_status": "Verification review: {reason}.",
    "line_relationship": "Recorded {relationship}: {attacker}; intervening piece: {front}; rear target: {rear}.",
    "line_endpoint": "Recorded {relationship}: {attacker}; rear target: {rear}.",
    "material": "Recorded retained material gain: {value} cp ({pov} perspective).",
    "evaluation_cp": "Recorded {stage} evaluation: {value} cp ({pov} perspective).",
    "evaluation_mate": "Recorded {stage} evaluation: signed mate distance {value} ({pov} perspective).",
    "timing": "Recorded payoff timing: {timing}.",
    "exchange_short": "Short tactical line: {line}",
    "exchange_line": "Exchange continuation ({state}): {line}",
    "exchange_balanced": "The material exchange is balanced in this continuation ({pov} perspective). This is not a free piece.",
    "exchange_material": "After the exchange: net material change {value} cp ({pov} perspective). This accounts for the whole line, not automatic Fork credit.",
    "exchange_incomplete": "Exchange settlement is incomplete ({reason}); retained material is not established.",
    "exchange_evaluation": "Recorded evaluation change versus the played move: {value} cp. This measures position quality, not material won.",
    "proof": "Stored line: {line}",
    "continuation": "Continuation: {line}.",
    "attribution": "{motif}: {attribution}",
    "teaching_note": "Follow the stored line from the decision position and compare it with the move played. The line is evidence for this example, not a claim about every possible defense.",
    "summary": "{title}{location}; recommended move {recommended}; played {played}.",
    "location": " on move {number}{color}",
    "alert": "{title}: {recommended}",
}

# Per-style data permits new deterministic styles without modifying UI code.
STYLES = {
    "concise_review": {"summary_template": "explanation", "detail_level": "concise", "include_evidence": False, "include_teaching_note": False},
    "teaching": {"summary_template": "explanation", "detail_level": "expanded", "include_evidence": True, "include_teaching_note": True},
    "alert": {"summary_template": "alert", "detail_level": "minimal", "include_evidence": False, "include_teaching_note": False},
    "summary": {"summary_template": "summary", "detail_level": "summary", "include_evidence": False, "include_teaching_note": False},
}

DEFAULT_PACK = {"schema_version": 1, "pack_id": "merlin_default", "name": "Merlin",
                "templates": COMMON, "styles": STYLES, "outcome_labels": OUTCOME_LABELS,
                "motif_labels": MOTIF_LABELS, "tactic_labels": TACTIC_LABELS}
