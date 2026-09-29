"""Disposable console test driver; not shipped in the consumer acceptance kit."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from tools.acceptance.console import Wizard, run_wizard
from tools.acceptance.windows import JobOwner


def simulate(wizard: Wizard) -> None:
    """Exercise console behavior without executing consumer operations.

    Args:
        wizard: A run explicitly marked simulation, never release evidence.
    """
    owner=JobOwner()
    try:
        wizard.say('SIMULATED ACTIONS ONLY; NO CHESSWIZARD INSTALL OR PROFILE ACCESS')
        wizard.step(1,'Checking synthetic environment')
        wizard.say('[1/8] Checking synthetic environment... PASS')
        wizard.step(2,'Simulated slow child')
        child=subprocess.Popen([os.path.join(os.environ['SystemRoot'],'System32/WindowsPowerShell/v1.0/powershell.exe'),
                                '-NoProfile','-Command','Start-Sleep -Seconds 7'],creationflags=subprocess.CREATE_NO_WINDOW)
        (wizard.record.folder/'owned-child-pid.txt').write_text(str(child.pid))
        while child.poll() is None:
            wizard.pulse();time.sleep(.1)
        wizard.step(3,'Synthetic manual checkpoint')
        wizard.ask('installer_ui','HUMAN CHECK PAUSE: this is only a synthetic console fixture.',True)
        wizard.step(8,'Synthetic completion')
        for gate in wizard.record.data['gates'].values():
            gate.update(status='PASS',evidence_kind='simulation',notes='Synthetic fixture; never acceptance evidence')
    finally:
        owner.stop_children()
        wizard.record.data['children_drained']=not owner.children()
        wizard.record.save()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--kit',type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(run_wizard(args.kit,simulate,scope='simulation'))
