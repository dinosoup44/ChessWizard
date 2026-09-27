"""Read-only candidate verification preview. No discovery or live apply option."""
import argparse
from collections import Counter
from contextlib import ExitStack, closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from analysis_engine import LazyScoutEngine
from analysis_safety import integrity_check
from analysis_settings import load_profile
from candidate_line_engine import CandidateLineGenerator
from candidate_line_repository import CandidateLineRepository
from candidate_line_service import CandidateLineService
from candidate_verification import existing_candidates, verify_candidates
from candidate_verification_registry import multiline_fork_verifier
from candidate_lines import to_data
from migrate_candidate_line_cache import migrate
from feedback import FeedbackContextBuilder, FeedbackGenerator
from tactical_opportunities import opportunity_to_dict

SOURCE_FILES = (
    'analysis_settings.py', 'candidate_line_request.py', 'candidate_line_engine.py',
    'candidate_line_service.py', 'candidate_line_repository.py', 'candidate_line_selection.py',
    'candidate_line_proof.py', 'quality_gate.py', 'the_scale.py', 'tactical_proof.py',
    'tactical_target_proof.py', 'analyze_forks_v3.py', 'analyze_forks_v3_multiline.py',
    'fork_robustness.py', 'candidate_verification_registry.py',
)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eligible_candidates(rows, coverage):
    keys = Counter((row['move_id'], row['tactic_type']) for row in rows)
    rejected = {row['move_id'] for row in coverage if row['coverage_status'] == 'rejected'}
    eligible, protected = [], Counter()
    for row in rows:
        if row['candidate_status'] != 'candidate':
            protected['rejected_or_nonactive'] += 1
        elif row['source'] == 'dev':
            protected['development_source'] += 1
        elif str(row['detector_version']) != '2':
            protected['version_exception'] += 1
        elif keys[(row['move_id'], row['tactic_type'])] != 1 or row['move_id'] in rejected:
            protected['canonical_or_coverage_conflict'] += 1
        else:
            eligible.append(row)
    return eligible, dict(protected)


def proposed_feedback(row, result):
    if result.opportunity is None:
        return None
    proposal = {**row, **(result.candidate or {}), 'solution_line': result.opportunity.proof.line_san}
    context = FeedbackContextBuilder().build(proposal, result.opportunity)
    return asdict(FeedbackGenerator().generate(context))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', choices=('missed_fork',), required=True)
    parser.add_argument('--profile', choices=('normal',), default='normal')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    reports, database = root/'reports', root/'merlin.db'
    profile = load_profile(args.profile)
    started = time.perf_counter()
    baseline_hash = file_hash(database)
    sources = {name: file_hash(root/name) for name in SOURCE_FILES}
    previous = json.loads((reports/'fork_v3_final_preview.json').read_text())
    previous_classes = {cid: state for state, ids in previous['candidate_ids_by_classification'].items() for cid in ids}
    with ExitStack() as stack:
        live = stack.enter_context(closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)))
        live.row_factory = sqlite3.Row
        live.execute('PRAGMA query_only=ON')
        integrity_check(live)
        rows = existing_candidates(live, args.analysis)
        coverage = [dict(row) for row in live.execute('SELECT * FROM analysis_coverage WHERE analysis_type=?', (args.analysis,))]
        counts = {table: live.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in
                  ('tactic_candidates', 'training_attempts', 'analysis_coverage', 'engine_position_cache')}
        ids = [row[0] for row in live.execute('SELECT candidate_id FROM tactic_candidates ORDER BY candidate_id')]
        eligible, protected = eligible_candidates(rows, coverage)
        # Mandatory supplied regression first; this is validation ordering, not an analyzer rule.
        eligible.sort(key=lambda row: (row['candidate_id'] != 1828, row['candidate_id']))
        before = {'database_sha256': baseline_hash, 'counts': counts, 'all_candidate_ids': ids,
                  'fork_rows': rows, 'fork_coverage': coverage, 'profile': asdict(profile),
                  'protected': protected, 'source_hashes': sources}
        (reports/'fork_v3_multiline_before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
        scratch = stack.enter_context(closing(sqlite3.connect(':memory:')))
        migrate(scratch)
        service = CandidateLineService(CandidateLineGenerator(LazyScoutEngine(stack, root)),
            read_stores=(CandidateLineRepository(live),), write_store=CandidateLineRepository(scratch))
        print(json.dumps({'eligible': len(eligible), 'protected': protected, 'profile': asdict(profile)}), flush=True)
        totals, metrics, changes, saved = Counter(), Counter(), Counter(), []
        with (reports/'fork_v3_multiline_results.jsonl').open('w', encoding='utf-8') as output:
            def record(row, result, completed, total):
                classification = result.details.get('classification', result.state)
                totals[classification] += 1
                details = result.details
                for key in ('root_move_passes_gate', 'forced_deterioration', 'geometric_vs_realizable_differ'):
                    metrics[key] += int(details.get(key) is True)
                metrics['root_move_fails_gate'] += int(details.get('root_move_passes_gate') is False)
                metrics['incomplete_evidence'] += int('incomplete' in details.get('reason', '') or bool(details.get('incomplete_evidence')))
                old = previous_classes.get(row['candidate_id'])
                if old != classification:
                    changes['classification_changed'] += 1
                if old == 'ambiguous' and classification in {'verified', 'verified_payoff_changed', 'rejected'}:
                    changes['ambiguity_resolved'] += 1
                if old in {'verified', 'verified_payoff_changed', 'rejected'} and classification == 'ambiguous':
                    changes['ambiguity_increased'] += 1
                record = {'candidate_id': row['candidate_id'], 'game_id': row['game_id'],
                    'source_game_id': row['source_game_id'], 'move_number': row['move_number'], 'color': row['color'],
                    'old_single_line_classification': old, 'state': result.state, 'details': details,
                    'candidate': result.candidate, 'opportunity': opportunity_to_dict(result.opportunity) if result.opportunity else None,
                    'feedback': proposed_feedback(row, result)}
                output.write(json.dumps(record)+'\n')
                output.flush()
                saved.append(record)
                if row['candidate_id'] == 1828:
                    (reports/'fork_v3_multiline_qxb7.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
                progress = {'completed': completed, 'total': total, 'outcomes': dict(totals),
                            'cache': dict(service.stats), 'elapsed_seconds': round(time.perf_counter()-started, 2)}
                (reports/'fork_v3_multiline_progress.json').write_text(json.dumps(progress, indent=2), encoding='utf-8')
                print(json.dumps(progress), flush=True)
            verify_candidates(eligible, multiline_fork_verifier(profile), service, record)
        integrity_check(live)
        assert live.total_changes == 0
        assert rows == existing_candidates(live, args.analysis)
        assert ids == [row[0] for row in live.execute('SELECT candidate_id FROM tactic_candidates ORDER BY candidate_id')]
        assert counts == {table: live.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in counts}
        assert baseline_hash == file_hash(database)
        assert sources == {name: file_hash(root/name) for name in SOURCE_FILES}
        scratch.commit()
        cache_rows = scratch.execute('SELECT count(*) FROM engine_candidate_line_cache').fetchone()[0]
        payload_bytes = scratch.execute('SELECT COALESCE(sum(length(CAST(payload_json AS BLOB))),0) FROM engine_candidate_line_cache').fetchone()[0]
        storage_bytes = scratch.execute('PRAGMA page_count').fetchone()[0] * scratch.execute('PRAGMA page_size').fetchone()[0]
        summary = {'total_existing_fork_rows': len(rows), 'eligible_active_candidates': len(eligible),
            'protected': protected, 'profile': asdict(profile), 'outcomes': dict(totals),
            'metrics': dict(metrics), 'compared_with_single_line': dict(changes), 'cache': dict(service.stats),
            'cache_rows': cache_rows, 'cache_payload_bytes': payload_bytes, 'scratch_database_bytes': storage_bytes,
            'counts_before': counts, 'counts_after': counts, 'all_candidate_ids_preserved': len(ids),
            'database_sha256_before': baseline_hash, 'database_sha256_after': file_hash(database),
            'live_database_writes': 0, 'quick_check': 'ok', 'foreign_key_check': [],
            'source_hashes': sources, 'elapsed_seconds': time.perf_counter()-started,
            'candidate_ids_by_classification': {state: [r['candidate_id'] for r in saved if r['details'].get('classification', r['state']) == state] for state in totals}}
        (reports/'fork_v3_multiline_preview.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in summary.items() if k not in {'candidate_ids_by_classification', 'source_hashes'}}, indent=2), flush=True)


if __name__ == '__main__':
    main()
