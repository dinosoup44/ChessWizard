"""Generic existing-ID reconciliation, tested on fixtures; no live entry point."""
import json
from heavy_repository import CANDIDATE_FIELDS, repository_authorizer
from tactical_opportunity_repository import prepare_opportunity_payload


def reconcile_candidate(connection, definition, expected, result, allowed_ids):
    cid = expected["candidate_id"]
    if cid not in allowed_ids: raise ValueError("Candidate is outside authorized reconciliation IDs")
    if result.state=="error": return {"action":"protected_retryable","candidate_id":cid}
    if result.state not in {"candidate","analyzed_no_hit"}: raise ValueError("Invalid result")
    connection.set_authorizer(repository_authorizer)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("SELECT * FROM tactic_candidates WHERE candidate_id=?",(cid,)).fetchone()
        if current is None: raise ValueError("Existing candidate disappeared; creation prohibited")
        if str(current["detector_version"])==definition.analyzer_version:
            connection.rollback();return {"action":"unchanged","candidate_id":cid}
        if int(current["detector_version"])>=int(definition.analyzer_version):
            raise ValueError("Newer or unknown detector version remains protected")
        for field in ("move_id","tactic_type",*CANDIDATE_FIELDS):
            if current[field]!=expected[field]: raise ValueError("Candidate changed since preview")
        if current["candidate_status"]!="candidate" or current["tactic_type"]!=definition.analysis_type:
            raise ValueError("Rejected or mismatched candidate remains protected")
        key = (current["move_id"],definition.analysis_type)
        rows = connection.execute("SELECT candidate_id FROM tactic_candidates WHERE move_id=? AND tactic_type=?",key).fetchall()
        if len(rows)!=1: raise ValueError("Ambiguous canonical identity")
        coverage = connection.execute("SELECT * FROM analysis_coverage WHERE move_id=? AND analysis_type=?",key).fetchone()
        if coverage is not None and (coverage["coverage_status"]=="rejected" or coverage["candidate_id"] not in (None,cid)):
            raise ValueError("Conflicting/rejected coverage remains protected")
        if coverage is not None and int(coverage['analyzer_version'])>=int(definition.analyzer_version):
            raise ValueError("Coverage is newer/current while candidate snapshot is stale")
        if result.state=="candidate":
            if result.candidate.get('candidate_status')!='candidate':
                raise ValueError("Candidate result/status mismatch")
            if str(result.candidate.get("detector_version"))!=definition.analyzer_version:
                raise ValueError("Version mismatch")
            if result.candidate.get("solution_move_uci")!=current["solution_move_uci"]:
                raise ValueError("Targeted verification cannot replace the stored tactical move")
            payload = prepare_opportunity_payload(result.candidate,result.opportunity,expected,current)
            # Codec merges unrelated old metadata when an opportunity is supplied.
            status = "candidate"
        else:
            payload = {field:current[field] for field in CANDIDATE_FIELDS}
            metadata = json.loads(current["metadata_json"] or "{}")
            metadata["heavy_reconciliation"] = result.details
            payload.update(candidate_status="rejected",detector_version=definition.analyzer_version,
                           metadata_json=json.dumps(metadata,sort_keys=True))
            status = "rejected"
        connection.execute("UPDATE tactic_candidates SET "+",".join(f"{field}=?" for field in CANDIDATE_FIELDS)+" WHERE candidate_id=?",
                           (*[payload.get(field) for field in CANDIDATE_FIELDS],cid))
        details = json.dumps({"stage":"targeted_reconciliation",**result.details},sort_keys=True)
        if coverage is not None:
            # Heavy-only refresh must not claim fresh screening/scouting.
            connection.execute("UPDATE analysis_coverage SET coverage_status=?,analyzer_version=?,candidate_id=?,details_json=?,checked_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE move_id=? AND analysis_type=?",
                               (status,definition.analyzer_version,cid,details,*key))
        else:
            connection.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,screener_version,scout_version,scout_config,analyzer_version,candidate_id,details_json) VALUES(?,?,?,'0','0','',?,?,?)",
                               (*key,status,definition.analyzer_version,cid,details))
        connection.commit()
        return {"action":"updated_in_place","candidate_id":cid,"state":status}
    except BaseException:
        connection.rollback();raise
    finally:
        connection.set_authorizer(None)
