# First public repository checklist

These are **instructions for later**, not actions already performed. No GitHub
repository, remote, commit, tag, push or release has been created by this readiness task.

## Before Git commands

1. Enable [two-factor authentication](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/configuring-two-factor-authentication) on your GitHub account and save recovery codes
   somewhere private. Never put recovery codes or tokens in the project.
2. Create an **empty** ChessWizard repository on GitHub. Do not add a conflicting
   GitHub-generated README, license or `.gitignore` when the local versions are ready.
3. Review the local `reports/PUBLIC_REPOSITORY_READINESS_V1.md` and
   [public-source boundaries](PUBLIC_SOURCE.md). **Stop while blockers remain.**
4. Review the existing GPL-3.0-or-later code license and the owner's CC0-1.0 icon
   dedication. Preserve the icon provenance/legal text and third-party notices.
5. Repeat the public-copy full suite, normal working-tree suite, pydoc checks and
   source scan. See the local `reports/PUBLIC_BLOCKER_CLEANUP_V1.md` for closure evidence.
   Keep private historical audits and local privacy configuration outside public source.
6. Review the exact public file manifest, notices, source provenance and ignored-file
   behavior. Keep engines, DBs, profile libraries, caches, backups and private reports out.
7. Establish a private sensitive-security reporting route in the GitHub repository. See the [GitHub private vulnerability reporting setup](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

## Run in Windows PowerShell â€” only after review approval

Start in your checkout (example below). Replace placeholders; never include a token,
password or credential in a URL. Git Credential Manager or SSH handles authentication.

```powershell
Set-Location C:\Projects\ChessWizard
.\.venv\Scripts\python.exe -B tools\check_pydoc.py
.\.venv\Scripts\python.exe -B -m tools.public_source
if ($LASTEXITCODE -ne 0) { throw 'Resolve source review holds before continuing.' }
```

Read `build/public-source-manifest.json`. Check tests on the intended public copy, not
just your working directory with private fixtures available. When approved, initialize
Git **only if this folder is not already a repository**:

```powershell
git init -b main
git config user.name '<PUBLIC_AUTHOR_NAME>'
git config user.email '<YOUR_VERIFIED_OR_GITHUB_NOREPLY_EMAIL>'
git status --short --untracked-files=all
git status --short --ignored
```

The identity above is attached to public commits; choose a GitHub-provided noreply
address if you do not want to publish your personal email. It is not a login credential.
If a repository already exists, inspect its branch, remotes and history instead of
reinitializing it. Never use `git add -f` to bypass private-data exclusions.

Stage only the reviewed manifest paths, preserving filenames with spaces:

```powershell
$sourceManifest = Get-Content -Raw build/public-source-manifest.json | ConvertFrom-Json
$publicPaths = [string[]]($sourceManifest.files | ForEach-Object { $_.path })
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllLines((Join-Path $PWD 'build/public-paths.txt'), $publicPaths, $utf8NoBom)
git --literal-pathspecs add --pathspec-from-file=build/public-paths.txt
git status --short
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check
git diff --cached
```

Review all staged text and assets. There must be no unexpected databases, libraries,
credentials, personal games or screenshots. To undo accidental staging before the first
commit, use `git rm --cached -- '<path>'`; this keeps the local file. Fix the ignore rule
and recheck. Do not use `git clean` or delete local backups to make a status screen tidy.

Only after that review:

```powershell
git commit -m 'Prepare ChessWizard public source'
git log -1 --stat
git remote add origin '<YOUR_GITHUB_REPO_URL>'
git remote -v
git push -u origin main
```

Do not overwrite an existing remote and do not force-push. Verify the repository and
account shown by GitHub before authenticating. Review the uploaded files in the browser;
then clone into a new directory and repeat setup, tests and pydoc without local data.

Tag a milestone only after that verification and a separate version decision:

```powershell
git tag -a '<APPROVED_TAG>' -m 'Reviewed source milestone'
git push origin '<APPROVED_TAG>'
```

A source tag is optional. Create a downloadable release later if desired, after a fresh
binary/license/source-companion audit and owner approval. Never attach an old installer
merely because the source repository is now public. Preserve matching source access and
third-party notices for any binary distribution.
