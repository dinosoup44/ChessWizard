"""Console prompts tied to durable evidence, independent of installer actions."""
from __future__ import annotations
from collections.abc import Callable
import json
import time
from pathlib import Path
from tools.acceptance.records import RunRecord, previous_result
from tools.release_acceptance import required_gates


class IncompleteAcceptance(Exception):
    """Signal unobserved gates without presenting them as failed checks."""


class Console:
    """Present prompts through explicit input/output functions.

    Args:
        read: Blocking text input; injectable in tests.
        write: Visible output; injectable in tests.
    """

    def __init__(self, read: Callable[[str], str] = input, write: Callable[[str], None] = print) -> None:
        """Bind console I/O without creating runtime side effects.

        Args:
            read: Text input callback.
            write: Output callback.
        """
        self.read = read
        self.write = write

    def key(self, prompt: str) -> None:
        """Wait for a key or an explicit redirected input line.

        Args:
            prompt: Instruction displayed before waiting.

        Raises:
            KeyboardInterrupt: Ctrl+C cancels.
            EOFError: Input closes before acknowledgement.
        """
        import sys
        self.write(prompt)
        if sys.stdin.isatty():
            import msvcrt
            key = msvcrt.getwch()
            if key == '\x03':
                raise KeyboardInterrupt()
            if key in ('\x00', '\xe0'):
                msvcrt.getwch()
        else:
            self.read('')


class Wizard:
    """Keep each human answer and visible step tied to a durable run.

    Args:
        record: Durable run state.
        console: Visible prompts.
    """

    def __init__(self, record: RunRecord, console: Console) -> None:
        """Prepare progress without starting work.

        Args:
            record: Durable run state.
            console: Prompt implementation.
        """
        self.record = record
        self.console = console
        self.last_pulse = time.monotonic()

    def say(self, message: str) -> None:
        """Display and retain progress.

        Args:
            message: Plain tester-facing text.
        """
        self.console.write(message)
        self.record.event(message)

    def step(self, number: int, title: str) -> None:
        """Persist the current obligation before performing it.

        Args:
            number: One-based step in the eight-step workflow.
            title: Upcoming work description.
        """
        self.record.data['current_step'] = f'[{number}/8] {title}'
        self.record.save()
        self.say('\n'+self.record.data['current_step']+'...')

    def pulse(self) -> None:
        """Print progress every five seconds while work is active."""
        if time.monotonic()-self.last_pulse >= 5:
            self.say('Still working... '+self.record.data['current_step'])
            self.last_pulse = time.monotonic()

    def ask(self, key: str, instructions: str, gate: bool = False) -> str:
        """Pause for a Y/N observation and explanatory notes.

        Args:
            key: Stable checkpoint or existing release gate identifier.
            instructions: Exactly what the tester must inspect.
            gate: Populate the corresponding release-acceptance gate.

        Returns:
            Tester notes after a Y answer.

        Raises:
            RuntimeError: A checkpoint receives N.
            KeyboardInterrupt: Q or Ctrl+C cancels without claiming acceptance.
        """
        self.say('\n'+instructions)
        while True:
            answer = self.console.read('Did this pass? Y/N (Q cancels): ').strip().upper()
            if answer == 'Q':
                raise KeyboardInterrupt()
            if answer in {'Y', 'N'}:
                break
            self.say('Please enter Y or N. No answer has been recorded.')
        notes = self.console.read('What did you observe? (warning/log/screenshot names): ').strip()
        while not notes:
            notes = self.console.read('Please record an observation; do not guess: ').strip()
        self.record.data['answers'].append({'checkpoint': key, 'answer': answer, 'notes': notes})
        if gate:
            kind = ('simulation' if self.record.data['scope'] == 'simulation' else
                    'clean_windows_observed' if key in required_gates(self.record.data)[0] else 'human_observed')
            self.record.data['gates'][key] = {'status': 'PASS' if answer == 'Y' else 'FAIL',
                                               'evidence_kind': kind, 'notes': notes}
        self.record.save()
        if answer == 'N':
            raise RuntimeError('Manual checkpoint not accepted: '+key)
        return notes


def run_wizard(kit: Path, workflow: Callable[[Wizard], None], console: Console | None = None,
               scope: str = 'clean_windows') -> int:
    """Run foreground acceptance with durable failure/interruption handling.

    Args:
        kit: Writable result directory.
        workflow: Explicit consumer workflow; simulations use a separate test driver.
        console: Optional test I/O.
        scope: Simulations remain marked and cannot supply clean-machine evidence.

    Returns:
        Zero for completion, one for failure, two for interruption, three for
        unavailable durable storage. Release approval remains separate.
    """
    console = console or Console()
    try:
        prior = previous_result(kit)
        if prior:
            console.write('Previous validation run was incomplete.' if prior.get('status') == 'INCOMPLETE'
                          else 'Previous validation result: '+str(prior.get('status')))
            while True:
                choice = console.read('R = Restart, V = View previous result, Q = Quit: ').strip().upper()
                if choice == 'V':
                    console.write(json.dumps(prior, indent=2))
                    continue
                if choice == 'Q':
                    return 2
                if choice == 'R':
                    break
        record = RunRecord(kit, scope)
        wizard = Wizard(record, console)
    except (OSError, ValueError, KeyError) as error:
        console.write('VALIDATION FAILED: unable to create/read durable results: '+str(error))
        console.write('No installer was started. Use a writable kit folder and keep prior evidence.')
        console.key('Press any key to close.')
        return 3
    code = 2
    try:
        wizard.say('ChessWizard V1.5 FINAL ACCEPTANCE')
        if scope == 'simulation':
            wizard.say('SIMULATION ONLY - NOT CLEAN-MACHINE OR HUMAN ACCEPTANCE EVIDENCE')
        wizard.say('This test will guide you through:\n1. environment check\n2. clean install\n3. first launch\n4. plugin check\n5. repair checks\n6. uninstall/reinstall checks\n7. final receipt creation')
        wizard.say('Nothing important will continue silently after this window closes.\nPress Ctrl+C to cancel.\nCancel inside an active installer when possible; forced closure can leave the disposable installation incomplete.')
        console.key('Press any key to begin.')
        workflow(wizard)
        clean, human = required_gates(record.data)
        failed = [k for k in (*clean, *human) if record.data['gates'][k]['status'] == 'FAIL']
        if failed:
            raise RuntimeError('Failed acceptance gates: '+', '.join(failed))
        missing = [k for k in (*clean, *human) if record.data['gates'][k]['status'] != 'PASS']
        if missing:
            record.data['reason'] = 'Unobserved acceptance gates: '+', '.join(missing)
            raise IncompleteAcceptance(record.data['reason'])
        if record.data.get('children_drained') is not True:
            raise RuntimeError('Acceptance child processes have not drained')
        record.data.update(status='PASS', current_step='[8/8] Final receipt creation complete')
        record.save()
        code = 0
    except IncompleteAcceptance as error:
        record.data.update(status='INCOMPLETE', reason=str(error))
        record.save()
    except (KeyboardInterrupt, EOFError):
        record.data.update(status='INCOMPLETE', reason='Cancelled or input closed; no automatic resume.')
        record.save()
    except Exception as error:
        record.data.update(status='FAIL', reason=str(error))
        record.save()
        code = 1
    wizard.say('\n========================================')
    wizard.say('VALIDATION COMPLETE - PASS' if code == 0 else 'VALIDATION FAILED' if code == 1 else 'VALIDATION INCOMPLETE')
    wizard.say('========================================')
    if code:
        wizard.say('Failed/incomplete step: '+record.data['current_step']+'\n'+record.data.get('reason', ''))
    wizard.say('Receipt saved to:\n'+str(record.path)+'\nLog saved to:\n'+str(record.log)+'\nQuick result: '+str(kit/'VIEW-RESULT.txt'))
    wizard.say('Nothing is still running in the background.' if record.data.get('children_drained') else
               'No successful shutdown is certified. Read the receipt and close any test app windows.')
    wizard.say('Owner release approval is still required.' if code == 0 else 'Do not continue release approval.')
    try:
        console.key('Press any key to close.')
    except (KeyboardInterrupt, EOFError):
        pass
    return code
