"""Explicit human observations for final acceptance; missing evidence stays open."""
from __future__ import annotations
from tools.acceptance.console import Wizard

SECURITY_FIELDS = {
    'browser_warning': 'Browser warning',
    'smartscreen_warning': 'SmartScreen warning',
    'defender_alert': 'Defender alert',
    'run_anyway_required': 'More info / Run anyway required',
    'execution_blocked': 'Execution blocked',
}


def choose(wizard: Wizard, prompt: str, options: tuple[str, ...]) -> str:
    """Request one explicit answer, allowing cancellation without fabrication.

    Args:
        wizard: Current foreground run.
        prompt: Human-readable question.
        options: Allowed uppercase answers.

    Returns:
        One accepted answer.

    Raises:
        KeyboardInterrupt: The tester selects Q or cancels input.
    """
    while True:
        answer = wizard.console.read(prompt + ' (Q cancels): ').strip().upper()
        if answer == 'Q':
            raise KeyboardInterrupt()
        if answer in options:
            return answer
        wizard.say('Choose ' + '/'.join(options) + '. No answer was recorded.')


def record_review(wizard: Wizard, key: str, instructions: str) -> None:
    """Record PASS, FAIL or unobserved for a bounded visual review.

    Args:
        wizard: Current run and result destination.
        key: Required human gate identifier.
        instructions: Checklist the tester has actually inspected.
    """
    wizard.say(instructions)
    answer = choose(wizard, 'Y = passed, N = failed, U = not observed', ('Y', 'N', 'U'))
    notes = wizard.console.read('Observation or reason not reviewed: ').strip()
    while not notes:
        notes = wizard.console.read('Record a short observation: ').strip()
    kind = 'simulation' if wizard.record.data['scope'] == 'simulation' else 'human_observed'
    wizard.record.data['gates'][key] = {
        'status': {'Y': 'PASS', 'N': 'FAIL', 'U': 'PENDING'}[answer],
        'evidence_kind': kind, 'notes': notes,
    }
    wizard.record.data['answers'].append({'checkpoint': key, 'answer': answer, 'notes': notes})
    wizard.record.save()


def record_security(wizard: Wizard) -> None:
    """Record the actual transfer and Windows warnings without inferring success.

    Args:
        wizard: Current run; the exact candidate hashes are already recorded.
    """
    wizard.say('SECURITY OBSERVATIONS: record what actually happened to the exact candidate.\n'
               'USB copy may not reproduce browser/Internet-zone behavior. Never disable Windows security.\n'
               'Choose browser only if you tested the browser-downloaded candidate without removing its Internet-zone metadata.')
    transfer = choose(wizard, 'Candidate transfer: B = browser, U = USB, O = other/unknown', ('B', 'U', 'O'))
    observation = {'transfer': {'B': 'browser', 'U': 'usb', 'O': 'other'}[transfer]}
    for key, label in SECURITY_FIELDS.items():
        observation[key] = choose(wizard, label + ': Y/N/U (U = not observed)', ('Y', 'N', 'U'))
    notes = wizard.console.read('Exact warning text or none; transfer method and any limitations: ').strip()
    while not notes:
        notes = wizard.console.read('Record what you actually observed: ').strip()
    status = 'PASS'
    if transfer != 'B' or any(observation[key] == 'U' for key in SECURITY_FIELDS):
        status = 'PENDING'
    if observation['defender_alert'] == 'Y' or observation['execution_blocked'] == 'Y':
        status = 'FAIL'
    kind = 'simulation' if wizard.record.data['scope'] == 'simulation' else 'human_observed'
    wizard.record.data['security_observation'] = observation
    wizard.record.data['gates']['security_prompts'] = {'status': status, 'evidence_kind': kind, 'notes': notes}
    wizard.record.save()
    wizard.say('Download/security gate: ' + status + '. Warnings were recorded, not silently dismissed.')
    decision = choose(wizard, 'Tester signing recommendation: A = unsigned beta with clear notes, B = obtain signing, U = wait for more evidence', ('A', 'B', 'U'))
    wizard.record.data['signing_decision'] = {'A': 'unsigned_with_documentation', 'B': 'sign_before_release', 'U': 'pending'}[decision]
    wizard.record.data['signing_reason'] = wizard.console.read('Observed basis (owner decision is separate): ').strip()
    wizard.record.save()
