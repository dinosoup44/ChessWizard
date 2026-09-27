# ChessWizard 1.0.0-beta

ChessWizard is free/open-source software under **GPL-3.0-or-later**, without
warranty. See [LICENSE](LICENSE) and [COPYING.md](COPYING.md).

It uses python-chess (the `chess` library by Niklas Fiekas and contributors),
Pillow and the Python runtime. It includes the unmodified Stockfish 18 engine
by the Stockfish developers. Third-party terms and acknowledgements are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `licenses/`.

Exact Stockfish source and network identities, and the corresponding-source
release procedure, are in [source_info/SOURCE.md](source_info/SOURCE.md).
A distributable build must be supplied with its matching source companion or
an explicit working download beside the binary. No ChessWizard binary/source
release has been published yet; do not distribute this working checkout.

## Internal onedir rehearsal

Windows 10/11 x86-64; bundled Stockfish requires an AVX2-capable CPU.
Open ChessWizard.exe, then use View for Training, Appearance and Admin.
The shared runtime, engine and notices are under `_internal`. The first launch
creates a clean database under LocalAppData/ChessWizard; no personal data is bundled.
This rehearsal is not an approved external release. Manual DPI/visual acceptance
and the matching public source companion are still required before distribution.
