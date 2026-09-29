"""Foreground consumer-installer acceptance; no application runtime imports."""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import platform
import subprocess
import time
from tools.acceptance.console import Wizard
from tools.acceptance.records import checked_path, digest
from tools.acceptance.windows import JobOwner, local_app_data
from tools.acceptance.observations import choose, record_review, record_security
from tools.release_acceptance import FINAL_PLAN

PLUGIN_ID = 'org.chesswizard.example.material_inventory'
FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
CASES = {'candidate': ('1.0.0-beta', '1.0.0')}


class ConsumerRun:
    """Guide explicit consumer actions only after the clean-profile guard.

    Args:
        wizard: Durable visible interaction.
    """

    def __init__(self, wizard: Wizard) -> None:
        """Bind canonical consumer paths without writing them.

        Args:
            wizard: Current run.
        """
        self.wizard = wizard
        self.kit = wizard.record.kit
        local = local_app_data() if os.name == 'nt' else Path('/unsupported')
        self.app = local / 'Programs/ChessWizard'
        self.profile = local / 'ChessWizard'
        self.owner: JobOwner | None = None
        self.manifest: dict[str, str] = {}
        self.sequence = 0

    def quiet(self) -> None:
        """Refuse a running ChessWizard app/host before a servicing operation.

        Raises:
            RuntimeError: A named application process is still running.
        """
        completed = subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/tasklist.exe'), '/FO', 'CSV', '/NH'],
                                   capture_output=True, text=True, timeout=15,
                                   creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        names = {row[0].lower() for row in csv.reader(completed.stdout.splitlines()) if row}
        if names & {'chesswizard.exe', 'chesswizardpluginhost.exe', 'chesswizardservicing.exe'}:
            raise RuntimeError('ChessWizard is still open. Close it normally; the test will not close someone else\'s app.')

    def snapshot(self, plugins_only: bool = False) -> dict[str, str]:
        """Hash the disposable profile without traversing linked content.

        Args:
            plugins_only: Restrict snapshot to installed plugin bytes.

        Returns:
            Relative file hashes.
        """
        root = self.profile / 'plugins/installations' if plugins_only else self.profile
        if not root.exists():
            return {}
        checked_path(root.parent, root.name)
        result = {}
        for folder, directories, files in os.walk(root, followlinks=False):
            for name in [*directories, *files]:
                target = Path(folder)/name
                checked_path(root, target.relative_to(root).as_posix())
                if target.is_file():
                    result[target.relative_to(root).as_posix()] = digest(target, self.wizard.pulse)
        return result

    def package(self, relative: str) -> Path:
        """Recheck exact package bytes immediately before consumption.

        Args:
            relative: Manifest member.

        Returns:
            Verified contained file.

        Raises:
            ValueError: The member is missing, linked or has changed bytes.
        """
        path = checked_path(self.kit, relative)
        if relative not in self.manifest or not path.is_file() or digest(path, self.wizard.pulse) != self.manifest[relative]:
            raise ValueError('Package verification failed: '+relative)
        return path

    def process(self, command: list[str], label: str, expected: int | None = 0) -> str:
        """Launch a foreground-owned child and visibly wait for all descendants.

        Args:
            command: Exact executable and arguments; no shell evaluation.
            label: Friendly action label.
            expected: Required exit code, or None for a deliberate cancellation.

        Returns:
            Bounded captured console output.

        Raises:
            RuntimeError: Exit status is wrong or output is excessive.
            TimeoutError: A step exceeds the thirty-minute bound.
        """
        self.sequence += 1
        log = self.wizard.record.folder / (self.wizard.record.run_id+f'-{self.sequence:02d}.log')
        self.wizard.say(label+'\nA separate window may open. Complete it, close ChessWizard normally, then return here.\nLog: '+str(log))
        self.wizard.record.data['active_action'] = label
        self.wizard.record.save()
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        environment['PATH'] = os.pathsep.join((str(Path(os.environ['SystemRoot'])/'System32'), os.environ['SystemRoot']))
        started = time.monotonic()
        with log.open('wb') as output:
            child = subprocess.Popen(command, cwd=self.kit, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            while child.poll() is None or (self.owner and self.owner.children()):
                self.wizard.pulse()
                if time.monotonic()-started > 1800:
                    raise TimeoutError('Step exceeded 30 minutes: '+label)
                if log.stat().st_size > 2_000_000:
                    raise RuntimeError('Child output exceeded the safety limit')
                time.sleep(.1)
        if expected is not None and child.returncode != expected:
            raise RuntimeError(f'{label} returned {child.returncode}; see {log}')
        self.wizard.say(label+'... '+('completed; inspect the recorded cancellation' if expected is None else 'PASS'))
        return log.read_text(encoding='utf-8-sig', errors='replace')

    def setup(self, case: str, preserve: bool = True) -> None:
        """Run one exact consumer installer, retaining profile bytes on repair.

        Args:
            case: Known synthetic/candidate case identifier.
            preserve: Compare profile hashes before and after installation.

        Raises:
            RuntimeError: Setup changes profile data or frozen identity is wrong.
        """
        self.quiet()
        before = self.snapshot()
        version, api = CASES[case]
        exe = self.package(f'{case}/ChessWizard-{version}-Windows-x64-Setup.exe')
        self.wizard.say('INSTALLER CHECK: inspect the ChessWizard name/icon, normal per-user path, Desktop shortcut option, progress and Finished-page controls. Do not approve unexpected elevation.\n'
                        + ('Uncheck Launch ChessWizard on Finished for this repair/upgrade; we check preserved bytes before opening it.'
                           if preserve else 'Select Launch ChessWizard on Finished (it starts unchecked). Inspect first launch and default openings, then close the app normally.'))
        log = self.wizard.record.folder / (self.wizard.record.run_id+'-'+case+f'-setup-{self.sequence}.log')
        self.process([str(exe), '/LOG='+str(log)], 'Installing '+case)
        self.quiet()
        if preserve and self.snapshot() != before:
            raise RuntimeError('Installer changed profile bytes. Do not continue approval.')
        info = self.host('info')
        if info.get('application_version') != version or info.get('api_version') != api or info.get('frozen') is not True:
            raise RuntimeError('Installed frozen identity differs from the selected case')

    def host(self, *args: str, failure: bool = False) -> dict:
        """Run an explicit installed console-host operation.

        Args:
            args: Existing host CLI arguments.
            failure: Require an expected blocked invocation.

        Returns:
            Parsed structured host output.

        Raises:
            RuntimeError: Output contradicts the expected operation outcome.
        """
        exe = checked_path(self.app, 'ChessWizardPluginHost.exe')
        text = self.process([str(exe), *args, '--profile', str(self.profile)], 'Plugin '+args[0],
                            expected=None if failure else 0)
        result = json.loads(text)
        if failure and not result.get('error'):
            raise RuntimeError('Expected blocked plugin invocation did not fail')
        return result

    def desktop(self, instructions: str) -> None:
        """Open the installed UI and wait for normal closure.

        Args:
            instructions: Human actions to perform before closing.
        """
        self.wizard.say(instructions)
        self.process([str(checked_path(self.app, 'ChessWizard.exe'))], 'ChessWizard human check')
        self.quiet()

    def uninstall(self, label: str, full: bool = False, cancel: bool = False) -> None:
        """Launch the real uninstall UI; never pass a silent removal switch.

        Args:
            label: Evidence label.
            full: Tester must explicitly choose and confirm full removal.
            cancel: Tester must decline the second confirmation.

        Raises:
            RuntimeError: Removal/preservation differs from the selected contract.
        """
        self.quiet()
        before = self.snapshot()
        self.wizard.say('UNINSTALL CHECK: full-data removal must start UNCHECKED.'
                        + (' Select it, inspect categories and the exact disposable profile, then answer NO to the second confirmation.'
                           if cancel else ' Explicitly select full removal and confirm the second question ONLY for this disposable test profile.'
                           if full else ' Leave full removal UNCHECKED. The default must say your ChessWizard data will be kept.'))
        log = self.wizard.record.folder / (self.wizard.record.run_id+'-'+label+'.log')
        self.process([str(checked_path(self.app, 'unins000.exe')), '/LOG='+str(log)], label,
                     expected=None if cancel else 0)
        if cancel:
            if not (self.app/'ChessWizard.exe').is_file() or self.snapshot() != before:
                raise RuntimeError('Declined full-removal confirmation changed app/profile')
        elif full:
            if self.profile.exists() or (self.app/'ChessWizard.exe').exists():
                raise RuntimeError('Confirmed full removal did not remove the app/profile')
        elif (self.app/'ChessWizard.exe').exists() or self.snapshot() != before:
            raise RuntimeError('Default uninstall did not preserve the complete profile')

    def run(self) -> None:
        """Run the owner-approved remaining external checks in eight visible stages.

        Raises:
            RuntimeError: An automated or manual acceptance obligation fails.
        """
        w = self.wizard
        try:
            w.step(1, 'Checking environment')
            if os.name != 'nt' or not os.environ.get('LOCALAPPDATA') or os.environ.get('CHESSWIZARD_DATA_DIR'):
                raise RuntimeError('Use a clean Windows account without a custom ChessWizard data override.')
            if Path(os.environ['LOCALAPPDATA']).absolute() != self.profile.parent.absolute():
                raise RuntimeError('LOCALAPPDATA override differs from the Windows known folder. No installer will run.')
            if self.app.exists() or self.profile.exists():
                raise RuntimeError('Existing ChessWizard install/profile detected. Nothing was changed. Restore the disposable clean-machine snapshot before Restart.')
            self.quiet()
            self.owner = JobOwner()
            notes = w.ask('clean_environment', 'ENVIRONMENT CHECK\nIs this a genuinely clean/disposable Windows machine/account, with no ChessWizard source checkout and no Python/Git/VS Code needed?\nThis run will install and eventually remove ONLY its disposable ChessWizard test profile.')
            reviewer = w.console.read('Tester name or initials: ').strip()
            if not reviewer:
                raise RuntimeError('Reviewer identification is required')
            w.record.data['environment'].update(genuinely_clean_windows=True, source_checkout_absent=True,
                developer_tools_not_required=True, windows_build=platform.platform(), reviewer=reviewer, notes=notes, windows_edition=platform.win32_edition(), architecture=platform.machine())
            w.record.save()
            w.say('[1/8] Checking environment... PASS')

            w.step(2, 'Verifying package hashes')
            manifest = json.loads(checked_path(self.kit, 'KIT-MANIFEST.json').read_text(encoding='utf-8'))
            if manifest.get('plan_id') != FINAL_PLAN:
                raise ValueError('This is not the final external acceptance kit')
            entries = manifest['files']
            self.manifest = {row['path']: row['sha256'] for row in entries}
            if len(self.manifest) != len(entries):
                raise ValueError('Duplicate kit manifest entries')
            for name in self.manifest:
                self.package(name)
            w.record.data['artifacts'] = {
                'installer_sha256': self.manifest['candidate/ChessWizard-1.0.0-beta-Windows-x64-Setup.exe'],
                'source_sha256': self.manifest['ChessWizard-Final-Acceptance-Source.zip'],
                'plugin_sha256': self.manifest['plugins/chesswizard_example_plugin-1.0.0-py3-none-any.whl']}
            w.record.save()
            w.say('[2/8] Verifying package hashes... PASS')

            w.step(3, 'Launching installer')
            self.setup('candidate', preserve=False)
            w.ask('installer_ui', 'INSTALLER CHECK\nCorrect ChessWizard name/icon; normal path; Desktop option; progress; Finished Launch checkbox actually opens ChessWizard; no unexpected admin request?', True)
            w.ask('clean_install', 'CLEAN INSTALL CHECK\nOne Desktop shortcut, one Start Menu entry and one Installed Apps entry; expected user profile; no owner data?', True)

            w.step(4, 'Checking first launch')
            self.desktop('FIRST LAUNCH CHECK\nNo startup error; default openings available; fresh empty games.\nImport only this synthetic PGN: '+str(self.package('synthetic-game.pgn'))+'\nMake a disposable setting change and a small saved opening edit. Do not run analysis or Stockfish. Close normally.')
            w.ask('first_run', 'FIRST LAUNCH CHECK\nDid the normal UI, default openings and synthetic PGN work without source/developer tools? Did you save a test setting/opening edit and close normally?', True)

            w.step(5, 'Checking plugin workflow')
            wheel = str(self.package('plugins/chesswizard_example_plugin-1.0.0-py3-none-any.whl'))
            self.host('install', wheel)
            self.desktop('PLUGIN CHECK\nOpen the synthetic game. Tools > Plugins: sample listed disabled.\nCancel Enable once; then review and explicitly acknowledge trust. Run on Current Position and inspect the material/square results. Disable it, then close normally.')
            w.ask('plugin_trust_ui', 'Did the unchecked trust dialog/cancellation, explicit enable, material results and disable controls work clearly?', True)
            self.host('analyze', PLUGIN_ID, '--fen', FEN, failure=True)
            w.ask('plugin_lifecycle', 'Was the independent sample listed, explicitly enabled, run successfully with validated facts displayed, and then disabled?', True)

            w.step(6, 'Checking same-version repair')
            self.setup('candidate')
            self.desktop('REPAIR CHECK\nCheck your synthetic game, saved setting/opening edit and DISABLED sample are still present. Check no duplicate shortcuts. Close normally.')
            w.ask('same_version_repair', 'Repair preserved your profile and disabled plugin after restart, with no duplicate shortcuts/registration?', True)

            w.step(7, 'Checking uninstall and reinstall')
            self.uninstall('default-uninstall')
            w.ask('default_uninstall', 'Default clearly kept data; app, shortcuts and Installed Apps entry removed; complete profile retained?', True)
            self.setup('candidate')
            self.desktop('REINSTALL CHECK\nPrior synthetic game, saved setting/opening edit and disabled sample must return. Close normally.')
            w.ask('reinstall_preserve', 'Did reinstall restore the previous profile and expected plugin package/state?', True)
            self.uninstall('inspect-full-removal', cancel=True)
            w.ask('optional_removal_review', 'Full-removal option started OFF; second confirmation listed categories and the disposable path; answering NO preserved app/data?', True)
            w.ask('cancellation_errors', 'Trust and uninstall cancellation/error wording were clear and left data intact?', True)

            w.step(8, 'Recording security and focused DPI observations')
            record_security(w)
            for scale in (100, 125, 150):
                w.say(f'DPI {scale}%: use Windows display settings, then reopen the apps at the effective scale.\n'
                      'If Windows requires sign-out, leave this scale unobserved and use DPI-CHECKLIST.md later; do not restart the complete functional run.')
                ready = choose(w, f'Is {scale}% effective now? Y = inspect, U = record later', ('Y', 'U'))
                if ready == 'Y':
                    self.desktop('Inspect only the main app, Plugin Manager and trust dialog. Check readable labels, no clipping/overlap/missing buttons, and usable panes. Cancel the trust dialog; close normally.')
                    before = self.snapshot()
                    installer = self.package('candidate/ChessWizard-1.0.0-beta-Windows-x64-Setup.exe')
                    self.process([str(installer)], 'Inspect installer at current DPI; cancel before Install', expected=None)
                    self.process([str(checked_path(self.app, 'unins000.exe'))], 'Inspect uninstaller at current DPI; cancel on FIRST page', expected=None)
                    if self.snapshot() != before or not (self.app/'ChessWizard.exe').exists():
                        raise RuntimeError('DPI inspection/cancellation changed profile or removed the app')
                    record_review(w, 'dpi_'+str(scale), f'At {scale}%: main app, Plugin Manager, trust, installer and uninstaller readable; no clipping, overlap, missing buttons or unusable panes?')
                else:
                    w.record.data['gates']['dpi_'+str(scale)]['notes'] = 'Not observed in this run; supplemental DPI checklist required.'
                    w.record.save()
            self.quiet()
            w.ask('no_orphan_workers', 'All test windows are closed; no ChessWizard plugin worker remains in Task Manager?', True)

        finally:
            if self.owner:
                self.owner.stop_children()
                w.record.data['children_drained'] = not self.owner.children()
            else:
                w.record.data['children_drained'] = True
            w.record.save()


def consumer_workflow(wizard: Wizard) -> None:
    """Execute only the guarded consumer workflow.

    Args:
        wizard: Current foreground run.

    Raises:
        RuntimeError: A safety or acceptance check fails.
    """
    ConsumerRun(wizard).run()
