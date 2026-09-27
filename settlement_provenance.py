"""Faithful proof provenance and read-time normalization of branch settlement summaries."""
from copy import deepcopy
from dataclasses import dataclass, replace

from analysis_settings import GeneratorSettings, identity
from candidate_line_request import request_identity
from candidate_lines import to_data
from proof_escalation import verification_profile
from proof_evidence_state import proof_state
from settlement_cache import settlement_settings
from settlement_evidence import settlement_evidence, settlement_identity
from tactical_proof import BoundedProof, ProofStep, ProofWindow


@dataclass(frozen=True)
class ProofProvenance:
    """Requested evidence keys are not claims that physical production-cache rows exist.

    Legacy cache aliases can satisfy these requests. Recorded request lists contain
    newly issued requests for the retained attempt chain, not every reused prefix.
    """
    evidence_stage: str
    generator: GeneratorSettings
    engine_identity: str
    profile_currentness: str
    proof_window: ProofWindow
    policy_identity: str
    request_identities: tuple[tuple[str, str], ...]
    request_scope: str
    source: str
    schema_version: int = 1


def _matches_branch(branch, proof):
    if branch.get('final_fen') != proof['final_fen']:
        return False
    if proof_state(branch['proof_state'], branch.get('final_fen')) != proof_state(proof['state'], proof['final_fen']):
        return False
    if branch.get('proof_steps') is not None:
        return [s['uci'] for s in branch['proof_steps']] == [s['uci'] for s in proof['steps']]
    summary = branch.get('settlement_evidence')
    if summary:
        return list(summary['moves_uci']) == [s['uci'] for s in proof['steps']]
    return (branch.get('proof_line') or '').split()[1:] == [s['san'] for s in proof['steps']]


def branch_provenance(details, index, profile):
    """Use the proof actually retained by the branch, never a denied or unused recheck."""
    branch = details['branches'][index]
    attempts = [a for a in details.get('escalation_attempts', []) if a['branch_index'] == index]
    selected = next((a for a in reversed(attempts) if a.get('proof') and _matches_branch(branch, a['proof'])), None)
    if selected:
        window = ProofWindow(**selected['proof']['window'])
        stage = selected.get('evidence_stage', 'verification')
        proof_profile = verification_profile(profile)
        generator = proof_profile.generator
        if profile.escalation.settlement_extension.enabled:
            generator = settlement_settings(profile.escalation.verification, window.settlement_plies)
        proof_profile = replace(proof_profile, generator=generator, proof=replace(proof_profile.proof,
            user_moves=window.user_moves, settlement_plies=window.settlement_plies, quiet_plies=window.quiet_plies))
        selected_moves = [s['uci'] for s in selected['proof']['steps']]
        requests = []
        for attempt in attempts:
            proof = attempt.get('proof')
            if proof:
                moves = [s['uci'] for s in proof['steps']]
                if selected_moves[:len(moves)] == moves:
                    requests.extend(tuple(key) for key in attempt.get('request_identities', []))
            if attempt is selected:
                break
        requests = tuple(dict.fromkeys(requests))
        return ProofProvenance(stage, generator, request_identity(generator), proof_profile.currentness_identity,
            window, identity(profile.escalation), requests, 'recorded_requests_for_retained_attempt_chain',
            'retained_escalation_proof')
    if branch.get('evidence_stage') in {'verification', 'selective_settlement_extension'}:
        raise ValueError('Verification summary lacks a matching retained proof; provenance cannot be guessed')
    window = ProofWindow(user_moves=profile.proof.user_moves, settlement_plies=profile.proof.settlement_plies,
        quiet_plies=profile.proof.quiet_plies)
    return ProofProvenance('breadth', profile.generator, request_identity(profile.generator), profile.currentness_identity,
        window, identity(profile.proof), (), 'individual_breadth_requests_not_recorded', 'breadth_branch_proof')


def branch_settlement_summary(details, index, player, profile):
    """Return corrected metadata while retaining the existing summary's chess content."""
    branch = details['branches'][index]
    steps = tuple(ProofStep(**step) for step in branch.get('proof_steps', []))
    existing = branch.get('settlement_evidence')
    if not steps and existing is None:
        return None
    provenance = branch_provenance(details, index, profile)
    if existing is not None:
        if steps and (list(existing['moves_uci']) != [s.uci for s in steps]
                or existing['final_fen'] != branch['final_fen']):
            raise ValueError('Stored settlement facts do not match the retained branch')
        summary = deepcopy(existing)
    else:
        # Preserve the public summary's existing score availability and perspective.
        raw = {}
        if 'final_player_cp' in branch:
            raw = dict(score_type='cp', score_pov='white',
                score_cp=branch['final_player_cp'] * (1 if player == 'white' else -1))
        proof = BoundedProof(branch['proof_state'], steps, branch['final_fen'], raw, provenance.proof_window)
        summary = to_data(settlement_evidence(steps[0].before_fen, player, proof,
            profile_identity=provenance.engine_identity, evidence_requests=provenance.request_identities))
    summary['proof_profile_identity'] = provenance.engine_identity
    summary['evidence_requests'] = to_data(provenance.request_identities)
    summary['branch_identity'] = settlement_identity(summary['base_fen'], summary['moves_uci'],
        provenance.engine_identity, provenance.request_identities, provenance.proof_window, summary['material_profile'])
    summary['provenance'] = to_data(provenance)
    return summary


def normalized_settlement_summaries(details, player, profile):
    """Normalize report payloads without changing their source or any analyzer verdict."""
    result = deepcopy(details)
    for index, branch in enumerate(result.get('branches', [])):
        summary = branch_settlement_summary(result, index, player, profile)
        if summary is not None:
            branch['settlement_evidence'] = summary
    return result
