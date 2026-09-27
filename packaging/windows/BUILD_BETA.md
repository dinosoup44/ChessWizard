# Rebuilding this beta

The source companion contains the exact locally consumed ChessWizard runtime source snapshot. No Git commit is claimed. SOURCE-MANIFEST.json hashes each included file; source_info/frozen_manifest.json identifies the original frozen files/modules. All third-party licenses retain their terms.

On Windows 10/11 x64, install CPython 3.14.7 AMD64 (the matching source is included under Upstream). From ChessWizard/:

```powershell
python -m venv build/windows/venv
build/windows/venv/Scripts/python.exe -m pip install -r packaging/windows/requirements-build.lock.txt
```

Place the official Stockfish 18 AVX2 executable at Engines/Stockfish/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe. Its required SHA256 is c86215fa1977d53b82ed854540a4c7b025be4cd042276c85ba3de53fb9118911. The exact source archive, both networks and upstream instructions are included under Upstream/Stockfish-18. To build Stockfish, extract the source, place both .nnue files beside its src/Makefile and follow its documented x86-64-avx2 build target. Rebuilding an upstream binary may change binary hashes; identify/review such a change explicitly.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -Rehearsal rehearsal-beta-installer
```

This uses a process-only execution-policy setting; it does not change the machine policy. The build is ONEDIR and uses only the pinned runtime and explicit resources. The local unshipped QA harness is not needed to build the tester application; do not use -Smoke from this source companion. The inherited four Admin documentation excerpts are included exactly as packaged.

To rebuild the installer, download the signed Inno Setup 6.7.3 installer from the URL pinned in packaging/windows/installer-toolchain.json, verify its SHA256 and Pyrsys B.V. signature, and install its compiler into build/windows/installer-tools/inno-6.7.3. Then:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/build-installer.ps1 -PayloadDir dist/ChessWizard-1.0.0-beta-rehearsal-beta-installer
```

The approved PNG and its ICO conversion are in packaging/windows/assets/. The centralized label remains 1.0.0-beta. The installer has a stable AppId, per-user install location, desktop shortcut enabled by default and a Start Menu entry. User data is separate. For future upgrades, retain that AppId and path, refresh the exact payload inventory and rehearse data-preserving uninstall/reinstall or an audited in-place upgrade. No arbitrary recursive user-data deletion is part of setup/uninstall. Check schema compatibility before publishing a future build; this beta does not add auto-migration of unrelated legacy user databases.

No bit-for-bit reproducibility claim is made: toolchain/PE timestamps may differ. Matching current source and exact dependency/provenance are provided. No personal data, developer environment, QA datasets, report logs or credentials are included.
