"""Run unittest discovery with isolated profile data and offscreen desktop fixtures."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


def _no_engine(event: str, args: tuple) -> None:
    if event == 'subprocess.Popen' and 'stockfish' in str(args[:2]).casefold():
        raise RuntimeError('Test runner forbids real engine processes')


def main(argv: list[str] | None = None) -> int:
    """Collect or run the complete available suite without a real engine or owner profile.

    Args:
        argv: Optional arguments; supports --collect-only and --pattern.

    Returns:
        Zero for clean collection and successful tests, otherwise one.
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect-only',action='store_true')
    parser.add_argument('--pattern',default='test_*.py')
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    sys.addaudithook(_no_engine)
    os.environ.pop('CHESSWIZARD_TEST_REAL_ANALYSIS',None)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    with tempfile.TemporaryDirectory(prefix='chesswizard-test-profile-') as profile:
        previous=os.environ.get('CHESSWIZARD_DATA_DIR')
        os.environ['CHESSWIZARD_DATA_DIR']=profile
        try:
            import tkinter as tk
            errors=[]
            original_init=tk.Tk.__init__
            original_error=tk.Tk.report_callback_exception
            def offscreen(window, *values, **kwargs):
                original_init(window,*values,**kwargs)
                window.geometry('+20000+20000')
            def callback_error(window,*values):
                errors.append(type(values[1]).__name__)
                original_error(window,*values)
            tk.Tk.__init__=offscreen
            tk.Tk.report_callback_exception=callback_error
            try:
                loader=unittest.TestLoader()
                suite=loader.discover(str(root/'tests'),pattern=args.pattern)
                if args.collect_only:
                    print(json.dumps({'collected':suite.countTestCases(),'collection_errors':loader.errors},indent=2))
                    return int(bool(loader.errors))
                result=unittest.TextTestRunner(verbosity=1).run(suite)
                print('Tk callback errors:',len(errors))
                return int(not result.wasSuccessful() or bool(errors))
            finally:
                tk.Tk.__init__=original_init
                tk.Tk.report_callback_exception=original_error
        finally:
            if previous is None:os.environ.pop('CHESSWIZARD_DATA_DIR',None)
            else:os.environ['CHESSWIZARD_DATA_DIR']=previous


if __name__=='__main__':
    raise SystemExit(main())
