"""Snapshot and compare experiment writes without changing schema or stored history."""
import hashlib
from analysis_safety import integrity_check, coverage_rows


def digest_rows(connection,table,where="",parameters=()):
    digest=hashlib.sha256();count=0
    for row in connection.execute(f'SELECT * FROM "{table}" {where} ORDER BY rowid',parameters):
        digest.update(repr(tuple(row)).encode());digest.update(b"\n");count+=1
    return {"count":count,"sha256":digest.hexdigest()}


def snapshot(connection):
    integrity_check(connection)
    tables=[r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    caches={table:{"maximum":connection.execute(f'SELECT coalesce(max(rowid),0) FROM {table}').fetchone()[0],
                   **digest_rows(connection,table)} for table in ("engine_position_cache","engine_candidate_line_cache")}
    return {"tables":{t:digest_rows(connection,t) for t in tables if t not in (*caches,"tactic_candidates","analysis_coverage")},
            "caches":caches,"candidates":{r["candidate_id"]:dict(r) for r in connection.execute("SELECT * FROM tactic_candidates")},
            "coverage":coverage_rows(connection)}


def verify(connection,before,allowed):
    integrity_check(connection)
    for table,value in before["tables"].items():
        if digest_rows(connection,table)!=value: raise RuntimeError(f"Protected table changed: {table}")
    candidates={r["candidate_id"]:dict(r) for r in connection.execute("SELECT * FROM tactic_candidates")}
    if any(candidates.get(cid)!=row for cid,row in before["candidates"].items()): raise RuntimeError("Existing candidate changed")
    new={cid:r for cid,r in candidates.items() if cid not in before["candidates"]}
    if any((r["move_id"],r["tactic_type"]) not in allowed for r in new.values()): raise RuntimeError("Out-of-scope candidate")
    coverage=coverage_rows(connection)
    if {k:v for k,v in coverage.items() if k not in allowed}!={k:v for k,v in before["coverage"].items() if k not in allowed}:
        raise RuntimeError("Out-of-scope coverage changed")
    for table,value in before["caches"].items():
        expected={k:v for k,v in value.items() if k!="maximum"}
        if digest_rows(connection,table,"WHERE rowid<=?",(value["maximum"],))!=expected: raise RuntimeError("Existing cache changed")
    duplicates=connection.execute("SELECT move_id,tactic_type,count(*) FROM tactic_candidates GROUP BY move_id,tactic_type HAVING count(*)>1").fetchall()
    if duplicates: raise RuntimeError("Duplicate canonical candidate identities")
    return {"new_candidate_ids":list(new),"existing_candidates_unchanged":len(before["candidates"]),
            "outside_scope_unchanged":True,"training_unchanged":True,"old_cache_rows_unchanged":True,
            "duplicates":0,"quick_check":"ok","foreign_key_check":[],
            "counts_after":{"tactic_candidates":len(candidates),"analysis_coverage":len(coverage),
                **{t:connection.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in before["caches"]}}}
