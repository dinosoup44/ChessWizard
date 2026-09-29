# Signing decision (owner decides after observations)

**A. Release unsigned beta:** fastest; document the absent signature and actual
warnings clearly. Suitable only if observed warnings are manageable, no unresolved
alert/block remains and the owner accepts the beta experience.

**B. Obtain code signing:** stronger publisher identity; added cost and process.
Signing does not instantly guarantee reputation or remove all warnings.
[Microsoft guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

Current decision: **pending actual security observations**. Development-PC install
success and USB-only success cannot establish the browser-download experience.
Prefer B if observed policy blocks or publisher-identity needs make A unsuitable.
Investigate any Defender alert; signing is not its remedy. Do not disable security.

Observed evidence / exact artifact: ______________________________________
Owner choice A/B: ______  Date: ______  Rationale: _________________________

Functional acceptance and distribution/signing policy are separate. Choosing A
or B does not fill missing clean-machine, DPI or security observations. No certificate
is purchased/configured by this kit. New signed/versioned bytes require affected
hash/package/source and acceptance checks again before a separately approved release.
