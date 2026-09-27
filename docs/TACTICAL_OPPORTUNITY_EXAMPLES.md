# Opportunity representations — examples only

These representations demonstrate the shared contract. They have **not** been
saved to historical candidates. New attribution and presentation choices are
editorial examples, not analyzer upgrades. Candidate IDs 1835 and 1836 still read
as legacy candidates with `opportunity=None` in the live database.

Full typed-codec-validated examples are in
`reports/tactical_opportunity_examples.json`; reproduce them with
`python -m reports.build_tactical_opportunity_examples` using the saved snapshot.
That script has no database or engine access.

| Example | Primary outcome | Primary mechanism | Secondary context | Timing / window | Presentation |
| --- | --- | --- | --- | --- | --- |
| 1835 | `win_pawn`, pawn | rook_pressure, supported | relative_pin and xray, context_only | immediate / 1 further user move | secondary_motif: Rook pressure wins a pawn |
| 1836 | `win_piece`, knight | check, supported | double_attack supported; relative_pin context_only | immediate / 1 | strong_callout: Check and win a knight |
| Future skewer | `win_exchange` | skewer, attribution unknown until proven | none required | immediate / 1 | strong_callout, hypothetical |
| Future delayed pin | `win_pawn`, pawn | absolute_pin, supported by cached line | removal_of_defender, supported | delayed / 4 | secondary_motif: unverified lead |

## Candidate 1835

Black played Bh6; the opportunity is Rab8. Proof: `Rab8 Ne2 Rxb2 O-O`.
Black-POV before/played/tactic scores: +361 / +138 / +295 cp; retained pawn:
+100 cp. Line relationship: black rook b8 → white pawn b2 → white knight b1;
direction `(0, -1)`. The pawn can move along the file. Do not claim it cannot
move or that the relative pin has been proved the decisive cause.

Suggested text: “Rab8 puts pressure on b2. In the engine line, Ne2 is met by
Rxb2, winning a pawn.” A secondary presentation level keeps this subtle example
quieter than a main missed-pin callout.

## Candidate 1836

White played Bf4; the opportunity is Qd5+. Proof: `Qd5+ Kc8 Qxc6 Re1+`.
White-POV before/played/tactic scores: +99 / -244 / +89 cp; retained knight:
+300 cp. Line relationship: white queen d5 → black knight c6 → black rook a8;
direction `(-1, 1)`. Check explains the forcing tempo; relative pin is context.

Suggested text: “Qd5+ checks the king and attacks the knight on c6. After Kc8,
Qxc6 wins the knight.”

For both historical examples, stored depth-18 final scores are retained in the
example's legacy evidence metadata. The examples leave settlement unknown rather
than interpreting an evaluated endpoint as a proven settled position.

## Future skewer

A future specialist can return `TacticalOutcome("win_exchange")` with a primary
`TacticalMotif("skewer")`. It supplies the attacker/front target/rear target as
`LineRelationship("skewer", ...)` only when those participants are established.
It must verify the defense and capture, then fill in causal rationale and proof.
The JSON example deliberately has no invented position, score, or defense claim.
This is a schema illustration, not a result eligible for candidate persistence
without the existing required candidate payload and legal solution.

## Future delayed pin

The existing read-only audit lead from game 139549965694, move 6 Black (move ID
176399), has `Qh4 c3 Bxh3 gxh3 Bxf2+ Kd1 f5 d3 f4 a4`. Queen h4 pins pawn f2
to king e1. The cached continuation shows +100 cp material retained after the
delayed capture, with a +170 cp root tactic score from Black's perspective.

The example records `delayed`, a four-further-user-move inspected window, and
supported attribution with explicit limits. Best-defense verification and
settlement remain unknown; no fresh alternative-defense or endpoint search was
performed. A future Pin V2 must establish those facts before promoting this
lead to a strong callout. This example does not implement Pin V2.
