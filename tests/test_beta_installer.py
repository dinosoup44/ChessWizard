"""Distribution safety contracts for the per-user Windows installer."""
from pathlib import Path
import unittest
import re
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

class BetaInstallerTests(unittest.TestCase):
    def section(self, name):
        text = (ROOT/'packaging/windows/ChessWizard.iss').read_text(encoding='utf-8-sig')
        text = re.sub(r'#ifdef FixtureRoot\n.*?#else\n(.*?)#endif', r'\1', text, flags=re.S)
        return text.split('['+name+']', 1)[1].split('\n[', 1)[0]

    def test_default_desktop_and_start_menu_use_same_installed_executable(self):
        task = next(line for line in self.section('Tasks').splitlines() if line.startswith('Name: desktopicon;'))
        self.assertNotIn('unchecked', task)
        icons = [line for line in self.section('Icons').splitlines() if line.startswith('Name:')]
        self.assertEqual(len(icons), 2)
        self.assertTrue(any('{userdesktop}\\ChessWizard' in line for line in icons))
        self.assertTrue(any('{userprograms}\\ChessWizard\\ChessWizard' in line for line in icons))
        self.assertTrue(all('Filename: "{app}\\ChessWizard.exe"' in line for line in icons))
        self.assertTrue(all('IconFilename: "{app}\\ChessWizard.exe"' in line for line in icons))

    def test_installer_never_targets_user_data_or_requires_admin(self):
        setup = self.section('Setup')
        self.assertIn('PrivilegesRequired=lowest', setup)
        self.assertIn('DefaultDirName={localappdata}\\Programs\\ChessWizard', setup)
        text = (ROOT/'packaging/windows/ChessWizard.iss').read_text(encoding='utf-8-sig')
        self.assertNotIn('[UninstallDelete]', text)
        self.assertNotIn('[InstallDelete]', text)
        self.assertNotIn('[Registry]', text)
        self.assertTrue(all('DestDir: "{app}' in line for line in self.section('Files').splitlines() if line.startswith('Source:')))

    def test_owner_artwork_has_required_windows_icon_sizes(self):
        with Image.open(ROOT/'packaging/windows/assets/ChessWizard.ico') as icon:
            self.assertEqual(icon.ico.sizes(), {(n,n) for n in (16,24,32,48,64,128,256)})
        self.assertIn('assets/ChessWizard.ico', (ROOT/'packaging/windows/ChessWizard.spec').read_text())

    def test_servicing_lifetime_and_full_removal_are_explicit(self):
        text=(ROOT/'packaging/windows/ChessWizard.iss').read_text(encoding='utf-8')
        self.assertIn('CloseApplications=no',self.section('Setup'))
        self.assertIn('AppMutex={code:ActivityMutex}',self.section('Setup'))
        self.assertIn('67CE3406-96D1-4EB6-AF71-3C95D925CF8B',text)
        self.assertIn('Choice.Checked := False',text)
        self.assertIn('Your ChessWizard data will be kept.',text)
        self.assertIn('MB_YESNO or MB_DEFBUTTON2',text)
        self.assertIn("if UninstallSilent then",text)
        self.assertIn('WizardForm.Close',text)
        self.assertIn('if Prepared and not Finalized',text)

    def test_servicing_validator_has_no_live_path_defaults(self):
        text=(ROOT/'tools/validate_upgrade.py').read_text(encoding='utf-8')
        for flag in ('--fixture','--profile','--receipts','--payloads','--wheel'):
            self.assertIn("'"+flag+"'",text)
        self.assertNotIn("/'Programs/ChessWizard'",text)
        wrapper=(ROOT/'packaging/windows/validate_installer.py').read_text(encoding='utf-8')
        self.assertNotIn('LOCALAPPDATA',wrapper)

    def test_lifetime_released_before_finished_page_launch(self):
        text=(ROOT/'packaging/windows/ChessWizard.iss').read_text(encoding='utf-8')
        step=text.split('procedure CurStepChanged',1)[1].split('procedure DeinitializeSetup',1)[0]
        self.assertIn('if CurStep = ssPostInstall then begin',step)
        self.assertIn('Finalized := True',step)
        self.assertIn('CloseHandle(ServicingHandle)',step)
        self.assertNotIn('ssDone',step)
