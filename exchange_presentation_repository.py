"""Read-only enrichment of legacy exchange details; missing cache never starts an engine."""
import json
from exchange_presentation import build_exchange_presentation, matching_tactical_continuation
from stored_line import StoredLine
from engine_cache import get_cached_position

class StoredExchangeReader:
    """Use only explicitly profiled, exact endpoint evidence already in the database."""
    def __init__(self, connection):
        self.connection=connection
        self.has_cache=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='engine_position_cache'").fetchone() is not None

    def enrich(self, row):
        try:
            metadata=json.loads(row.get('metadata_json') or '{}')
        except (ValueError, TypeError):
            return row
        if not isinstance(metadata,dict) or metadata.get('exchange_presentation') is not None:return row
        if metadata.get('detector')!='fork_v2_post_conversion':return row
        short=StoredLine.from_san(row.get('fen_before'),row.get('solution_line'))
        if not short.positions:return row
        profile=metadata.get('verify_profile')
        raw=None;continuation=None;source='missing_recorded_evidence'
        if self.has_cache and profile=='tactic_verify_v1':
            raw=get_cached_position(self.connection,short.positions[1],profile)
            if raw:
                continuation=matching_tactical_continuation(short.base_fen,short.raw_text,raw.get('principal_variation'))
                source='recorded_position_cache:'+str(raw['cache_id'])+':matched_tactical_pv'
            if continuation is None:
                raw=get_cached_position(self.connection,short.positions[-1],profile)
                continuation=(raw.get('principal_variation') or '') if raw else ''
                source='recorded_position_cache:'+str(raw['cache_id'])+':endpoint' if raw else 'missing_recorded_evidence'
        try:
            detail=build_exchange_presentation(short.base_fen,short.raw_text,continuation or '',
                evidence_source=source)
        except ValueError:
            detail=build_exchange_presentation(short.base_fen,short.raw_text,'',evidence_source='invalid_recorded_evidence')
        return {**row,'metadata_json':json.dumps({**metadata,'exchange_presentation':detail.to_dict()},sort_keys=True)}
