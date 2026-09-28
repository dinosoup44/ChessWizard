# Security and privacy

ChessWizard stores chess history, libraries, themes, settings and analysis locally.
Imports explicitly contact the selected chess provider; ordinary review of stored games
and offline PGN import do not require a cloud service. Local files can still contain
personal information, and backups or synchronized folders may copy it elsewhere.

For a **non-sensitive bug**, use the repository's GitHub Issues. Include
the version, operating system and minimal reproduction. Prefer synthetic chess positions.
Do not attach a private SQLite database, full game export, access token or unreviewed log.
Review screenshots for usernames, game links, file paths and private notes before posting.
Contributors must sanitize traces and fixtures before submitting issues or pull requests.

A private security-reporting contact has **not yet been established**. For a sensitive
vulnerability, do not post exploit details or secrets publicly. After the owner enables
GitHub private vulnerability reporting, use the repository's Security / Report a
vulnerability action. Until then, request a private reporting route without disclosing
the sensitive details. No email address or response-time promise is implied.

The owner must establish the sensitive-reporting route before inviting external users.
This document does not claim that the beta has received a formal security assessment.

## Plugin trust and distribution

Plugins execute with the user's permissions in separate bounded processes. They are
**not sandboxed**; install only artifacts you trust. Static discovery does not import
plugin code. Enabling acknowledges the exact artifact; replacements require new trust.
V1 allows pure-Python wheels using only the public SDK dependency and the declared
minimal import surface. Plugins cannot submit accepted tactics or own core databases.
Process limits and fact validation do not make malicious code safe.

Theme/community packs remain data and allowlisted assets only; they cannot install
plugins or scripts. Installer hashes detect changed bytes but do not authenticate a
publisher. Do not disable Defender, SmartScreen or browser security to install a build.
Release acceptance records the actual warnings and signing decision; see
[installation](docs/INSTALLATION.md) and the [release checklist](docs/FIRST_PUBLIC_RELEASE_CHECKLIST.md).
