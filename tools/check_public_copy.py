"""Rehearse collection and tests from exactly the candidate public source manifest."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.public_source import ROOT, source_manifest


def main(argv: list[str] | None = None) -> int:
    """Copy public candidates into temporary storage and exercise their own test entry point.

    Args:
        argv: Optional --collect-only switch; otherwise run collection and full tests.

    Returns:
        Zero only when all requested checks pass. Logs stay in ignored build output.

    Raises:
        OSError: Source copying or log creation fails.
        subprocess.TimeoutExpired: A rehearsal exceeds the twenty-minute bound.
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect-only',action='store_true')
    args=parser.parse_args(argv)
    output=ROOT/'build/public-copy-check'
    output.mkdir(parents=True,exist_ok=True)
    manifest=source_manifest(ROOT)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    statuses={}
    with tempfile.TemporaryDirectory(prefix='chesswizard-public-check-') as temporary:
        fresh=Path(temporary)/'source';fresh.mkdir()
        for entry in manifest['files']:
            target=fresh/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/entry['path'],target)
        assert not any((fresh/p).exists() for p in ('merlin.db','reports','review_data','reviews','tests/local_history','.venv','Engines'))
        env=os.environ.copy();env.pop('PYTHONPATH',None);env.pop('CHESSWIZARD_TEST_REAL_ANALYSIS',None)
        env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',CHESSWIZARD_DATA_DIR=str(Path(temporary)/'profile'))
        for label,options in [('collection',['--collect-only']),*([] if args.collect_only else [('suite',[])])]:
            with (output/(label+'.log')).open('w',encoding='utf-8') as log:
                result=subprocess.run([sys.executable,'-B','tools/run_tests.py',*options],cwd=fresh,
                    env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            statuses[label]=result.returncode
            print(label+': '+str(result.returncode),flush=True)
            if result.returncode:break
    receipt={'files':len(manifest['files']),'bytes':sum(e['bytes'] for e in manifest['files']),
        'checks':statuses,'private_files_present':False,'same_installed_dependencies':True}
    (output/'result.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return int(any(statuses.values()))


if __name__=='__main__':
    raise SystemExit(main())
