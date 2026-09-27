"""Compare objective recorded facts, never analyzer classifications or admission policy."""
from dataclasses import asdict
from collections import Counter
from pathlib import Path
import hashlib
import json
import time
import chess
from position_range_evidence import analyze_range
from proof_endpoint_facts import collect_endpoint_facts
from tests.support.position_range_parity_reference import replay_reference

TAXONOMY = dict(A="exact factual agreement", B="representation-only difference",
    C="expected semantic-scope difference", D="toolkit more precise", E="existing Fork evidence more precise",
    F="likely toolkit bug", G="likely existing Fork-helper bug", H="unresolved / manual review needed")


def compare_range(proposal: dict, recorded: dict) -> dict:
    """Cross-check supplied legal ranges against an independent replay oracle.

    Args:
        proposal: Supplied position, targets and material-value settings.
        recorded: Supplied line and previously recorded endpoint facts.

    Returns:
        Structured comparison or factual result for the supplied inputs.

    Raises:
        ValueError: Supplied files, positions or evidence fail the validation contract.
    """
    started = time.perf_counter()
    values = {chess.PIECE_NAMES.index(k): v for k,v in proposal['material_values'].items()}; values[chess.KING] = 0
    moves, targets = recorded['moves_uci'], proposal['targets']
    toolkit_started = time.perf_counter()
    evidence = analyze_range(proposal['fen_before'], moves, track_squares=targets,
                             piece_values=values, material_snapshots=True)
    toolkit_seconds = time.perf_counter()-toolkit_started
    reference = replay_reference(proposal['fen_before'], moves, values)
    old = recorded.get('existing_facts')
    old_origin = 'stored_endpoint_facts'
    if old is None:
        old = collect_endpoint_facts(proposal['fen_before'], moves[0], moves[1:], targets, values)
        old_origin = 'existing_factual_helper_on_recorded_line'
    comparisons = []
    def compare(field, old_value, new_value, independent, category='A', explanation=''):
        code = category if old_value == new_value == independent else (
            'G' if new_value == independent and old_value != independent else
            'F' if old_value == independent and new_value != independent else 'H')
        comparisons.append(dict(field=field, category=code, old=old_value, toolkit=new_value,
                                independent=independent, explanation=explanation))
    def precision(field, new_value, independent, explanation):
        comparisons.append(dict(field=field,category='D' if new_value==independent else 'F',
            old=None,toolkit=new_value,independent=independent,explanation=explanation))
    def scope(field, old_value, new_value, explanation):
        comparisons.append(dict(field=field,category='C',old=old_value,toolkit=new_value,
                                independent='compared on common factual scope elsewhere',explanation=explanation))
    player = reference['player']; index = 0 if player else 1
    balances = [s.for_color(player)-s.for_color(not player) for s in evidence.material_transition.snapshots]
    refbalances = [t[index]-t[1-index] for t in reference['timeline']]
    compare('endpoint_fen', old['endpoint_fen'], evidence.end_fen, reference['fen'])
    if recorded.get('existing_endpoint_fen'):
        compare('stored_proof_endpoint_fen',recorded['existing_endpoint_fen'],evidence.end_fen,reference['fen'])
    compare('material.delta_player',old['material_delta_cp'],balances[-1]-balances[0],refbalances[-1]-refbalances[0])
    compare('material.per_move_player_balance',[m['material_cp'] for m in old['moves']],balances[1:],refbalances[1:])
    before_old = old['moves'][-1]['material_cp']-old['material_delta_cp']
    compare('material.before_player_balance',before_old,balances[0],refbalances[0])
    compare('material.after_player_balance',old['moves'][-1]['material_cp'],balances[-1],refbalances[-1])
    compare('material.recent_balances',old['recent_material_cp'],balances[-4:],refbalances[-4:])
    def old_captures():
        result=[]
        for c in old['captures_since_tactic_start']:
            piece=chess.Piece.from_symbol(c['victim'])
            result.append([c['ply']+1,chess.parse_square(c['square']),piece.piece_type,piece.color,abs(c['signed_cp'])])
        return result
    new_captures=[[c.ply,c.square,c.victim_type,c.victim_color,c.value] for c in evidence.material_transition.captures]
    ref_captures=[[c['ply'],c['square'],c['victim_type'],c['victim_color'],c['value']] for c in reference['captures']]
    compare('material.capture_order_type_color_square_value',old_captures(),new_captures,ref_captures)
    selected_targets={chess.parse_square(square) for square in targets}
    old_capture_roles=[[c['original_target'],c['by_original_attacker']] for c in old['captures_since_tactic_start']]
    new_capture_roles=[[chess.square_name(c.victim.initial_square) if c.victim.initial_square in selected_targets else None,
                        c.capturer.initial_square==reference['attacker']] for c in evidence.material_transition.captures]
    ref_capture_roles=[[chess.square_name(c['victim']) if c['victim'] in selected_targets else None,
                        c['capturer']==reference['attacker']] for c in reference['captures']]
    compare('captures.original_target_and_attacker_roles',old_capture_roles,new_capture_roles,ref_capture_roles)
    old_promotions=[]
    for i,event in enumerate(old['moves']):
        move=chess.Move.from_uci(event['uci'])
        if move.promotion:
            previous=before_old if i==0 else old['moves'][i-1]['material_cp']
            signed_capture=sum(c['signed_cp'] for c in old['captures_since_tactic_start'] if c['ply']==i)
            delta=(event['material_cp']-previous-signed_capture)*(1 if i%2==0 else -1)
            old_promotions.append([i+1,move.promotion,delta])
    compare('material.promotion_change',old_promotions,[[p.ply,p.to_type,p.material_delta] for p in evidence.material_transition.promotions],
            [[p['ply'],p['to_type'],p['delta']] for p in reference['promotions']])
    if old_captures():
        compare('capture.ply_origin',[c['ply']+1 for c in old['captures_since_tactic_start']],
                [c.ply for c in evidence.material_transition.captures],[c['ply'] for c in reference['captures']],
                'B','Old ledger uses zero-based root ply; toolkit uses one-based plies.')
    precision('material.side_totals',[[s.white,s.black] for s in (evidence.material_transition.before,evidence.material_transition.after)],
              [list(reference['timeline'][0]),list(reference['timeline'][-1])],'Old endpoint artifact exposes player balance, not separate color totals.')
    precision('material.promotion_ledger',[[p.ply,p.piece.initial_square,p.to_type,p.material_delta] for p in evidence.material_transition.promotions],
              [[p['ply'],p['piece'],p['to_type'],p['delta']] for p in reference['promotions']], 'Promotion is implicit in old move/material ledger.')
    precision('captures.original_identities_ep',[[c.victim.initial_square,c.capturer.initial_square,c.en_passant,c.destination] for c in evidence.material_transition.captures],
              [[c['victim'],c['capturer'],c['en_passant'],c['destination']] for c in reference['captures']], 'Old captures name current victim and optional original-target flag, not all original piece IDs.')
    fates={f.piece.initial_square:f for f in evidence.tracked_piece_fates}
    old_targets={chess.parse_square(t['original_square']):t for t in old['original_target_fates']}
    for original,t in old_targets.items():
        f=fates[original];r=reference['fates'][original];prefix='target.'+chess.square_name(original)
        current=chess.parse_square(t['current_square']) if t['current_square'] else None
        compare(prefix+'.square',current,f.current_square,r['current_square'])
        compare(prefix+'.captured',t['fate']=='captured',not f.alive,r['capture_ply'] is not None)
        capture_record=next((c for c in old['captures_since_tactic_start'] if c['original_target']==chess.square_name(original)),None)
        compare(prefix+'.capture_ply',capture_record['ply']+1 if capture_record else None,f.capture_ply,r['capture_ply'])
        compare(prefix+'.attacked',t['attacked_by_player'],bool(f.attack_state and f.attack_state.attacked),bool(r['attackers']))
        precision(prefix+'.identity_and_history',[f.piece.initial_square,f.piece.initial_piece_type,f.piece.color,f.capture_ply,
                  f.captured_by.initial_square if f.captured_by else None,f.move_count,f.promoted,f.final_piece_type],
                  [original,chess.Board(proposal['fen_before']).piece_type_at(original),r['color'],r['capture_ply'],r['captured_by'],r['move_count'],r['promoted'],r['piece_type']],
                  'Old endpoint location objects omit full identity/movement/promotion history; capture ply from the separate old capture ledger is compared independently.')
        if f.attack_state:
            precision(prefix+'.defenders',list(f.attack_state.geometric_defenders),r['defenders'],'Old endpoint target facts omit defenders.')
        if current==original and f.moved:
            scope(prefix+'.moved_label',t['fate'],f.move_count,'Still on original square describes endpoint location; it does not imply never moved.')
    attacker=evidence.attacker_survival;f=attacker.fate;r=reference['fates'][reference['attacker']]
    compare('attacker.square',chess.parse_square(old['attacker_square']) if old['attacker_square'] else None,f.current_square,r['current_square'])
    compare('attacker.captured',old['attacker_fate']=='captured',not f.alive,r['capture_ply'] is not None)
    compare('attacker.attacked',old['attacker_attacked'],bool(f.attack_state and f.attack_state.attacked),bool(r['attackers']))
    precision('attacker.identity_history_destination',[f.piece.initial_square,attacker.destination_after_tactic,f.capture_ply,
              f.captured_by.initial_square if f.captured_by else None,f.move_count,attacker.moved_again,f.promoted,f.final_piece_type],
              [reference['attacker'],reference['tactic_destination'],r['capture_ply'],r['captured_by'],r['move_count'],r['move_count']>1,r['promoted'],r['piece_type']],
              'Old endpoint facts contain survival/location but not a full original-piece history.')
    tracked={t.current_square for t in evidence.tracked_piece_fates if t.current_square is not None}
    if evidence.moves[-1].capture:
        tracked.add(evidence.moves[-1].capture.destination)
    common=[o for o in evidence.relevant_recaptures if o.capture.victim_square in tracked]
    reference_common=[c for c in reference['legal_captures'] if c['square'] in tracked]
    compare('recapture.common_legal_scope',sorted(old['legal_relevant_capture_or_recapture_options']),
            sorted(o.capture.san for o in common),sorted(c['san'] for c in reference_common))
    all_legal={c['uci']:c for c in reference['legal_captures']}
    precision('recapture.identity_value_side',[[o.capture.uci,o.capture.victim.initial_square,o.capture.capturer.initial_square,o.capture.value,o.capture.side_to_move] for o in evidence.relevant_recaptures],
        [[o.capture.uci,all_legal[o.capture.uci]['victim'],all_legal[o.capture.uci]['capturer'],all_legal[o.capture.uci]['value'],all_legal[o.capture.uci]['side']] for o in evidence.relevant_recaptures],
        'Old endpoint availability is a SAN list; toolkit adds original IDs, value, side, and relations.')
    extras=sorted(o.capture.san for o in evidence.relevant_recaptures if o not in common)
    if extras:
        scope('recapture.additional_participant_captures',[],extras,'Toolkit also reports legal captures by the attacker/exchange participants, beyond captures onto tracked squares.')
    for f in fates.values():
        if not f.attack_state:continue
        a=f.attack_state;r=reference['fates'][f.piece.initial_square]
        applicable = r['piece_type']==chess.KING or r['color'] != chess.Board(reference['fen']).turn
        expected=None if not applicable else sorted({chess.Move.from_uci(c['uci']).from_square for c in reference['legal_captures'] if c['victim']==f.piece.initial_square})
        precision('attack.legal_sources.'+chess.square_name(f.piece.initial_square),list(a.legal_attackers) if a.legal_attackers is not None else None,expected,
                  'Geometric attack does not imply a king-safe capture; legal moves are for the actual side to move only.')
    compare('in_check',old['in_check'],evidence.terminal_state.in_check,reference['in_check'])
    old_terminal=recorded.get('stored_terminal') or old['terminal']
    old_ended=old_terminal['complete'];new_ended=evidence.terminal_state.is_terminal
    compare('terminal.automatic_ending',old_ended,new_ended,reference['terminal']!='not_terminal')
    old_result=old_terminal.get('result')
    new_result=('1-0' if evidence.terminal_state.winner else '0-1') if evidence.terminal_state.state=='checkmate' else '1/2-1/2' if new_ended else None
    compare('terminal.result',old_result,new_result,reference['terminal_result'])
    if new_ended:
        normalized_old = ('stalemate' if old_terminal['terminal_state']=='stalemate' else
                          'checkmate' if old_terminal['terminal_state'] in ('other_terminal','played_checkmate','candidate_checkmate') else
                          reference['terminal'] if old_terminal['terminal_state']=='draw_terminal' and reference['terminal'] in ('other_draw','insufficient_material') else old_terminal['terminal_state'])
        compare('terminal.label_normalization',normalized_old,evidence.terminal_state.state,reference['terminal'],
                'B','Old role/ownership labels or draw_terminal are normalized to the proved board rule; automatic ending/result checked separately.')
    else:
        scope('terminal.claim_or_history_detail',old_terminal['terminal_state'],evidence.terminal_state.state,
              'Old none means no automatic ending; toolkit additionally distinguishes claimability and unavailable earlier history.')
        precision('terminal.known_claims',[evidence.terminal_state.fifty_move_claimable,evidence.terminal_state.repetition_claimable],
                  [reference['fifty_claimable'],True if reference['repetition_claimable'] else False if proposal['fen_before']==chess.STARTING_FEN else None],
                  'Partial replay can prove a positive repetition, but cannot disprove an earlier missing history.')
    steps=recorded.get('proof_steps') or []
    if steps:
        if [s['uci'] for s in steps]==moves[1:]:
            for i,s in enumerate(steps,1):
                event=evidence.moves[i];ref=reference['steps'][i]
                recorded_fens=[s['before_fen'],s['after_fen']]
                reference_fens=[ref['before_fen'],ref['after_fen']]
                comparisons.append(dict(field=f'proof_step.{i}.fens',category='E' if recorded_fens==reference_fens else 'G',
                    old=recorded_fens,toolkit=None,independent=reference_fens,
                    explanation='Stored proof steps serialize per-ply FENs; RangeEvidence move events do not. Independent replay validates them; LegalReplay offers separate position queries.'))
                compare(f'proof_step.{i}.san',s['san'],event.san,ref['san'])
                if 'material_cp' in s:
                    compare(f'proof_step.{i}.material',s['material_cp'],balances[i+1],refbalances[i+1])
                compare(f'proof_step.{i}.capture',[s.get('captured_square'),s.get('captured_piece')],
                        [event.capture.square,event.capture.victim_type] if event.capture else [None,None],
                        next(([c['square'],c['victim_type']] for c in reference['captures'] if c['ply']==i+1),[None,None]))
        else:
            scope('proof_steps.retained_scope',len(steps),len(moves)-1,
                  'Serialized branch steps are from a different retained window; do not compare them as the endpoint range. Full endpoint ledger remains compared.')
    counts=Counter(c['category'] for c in comparisons)
    return dict(range_id=recorded['range_id'],proposal=proposal['key'],old_facts_origin=old_origin,
        toolkit_seconds=toolkit_seconds,normalization_parity_seconds=time.perf_counter()-started-toolkit_seconds,
        categories=dict(counts),comparisons=comparisons,serious=any(k in counts for k in ('F','G','H')),
        features=dict(attacker_alive=attacker.fate.alive,targets_moved=any(f.moved for f in evidence.tracked_piece_fates if f.piece.initial_square in old_targets),
            targets_captured=any(not f.alive for f in evidence.tracked_piece_fates if f.piece.initial_square in old_targets),
            recapture=bool(common),promotion=bool(evidence.material_transition.promotions),en_passant=any(c.en_passant for c in evidence.material_transition.captures),
            terminal=evidence.terminal_state.state,in_check=reference['in_check']))


