# Security policy — NLP coherence runtime

## Supported scope

The supported authority path is exclusively:

`NlpCoherenceRuntime.execute → EnvelopeVerifier.verify → EnvelopeVerifier.render_french`.

Historical NLP/coherence engines are not imported and cannot authorize this
runtime. A deployment must supply two independently configured trust stores:
frame-authority public keys and calibration-authority public keys. Test keys and
fixtures in `tests/` are never production trust roots.

## Security invariants

- Every required frame has exactly one signed K3 verdict: `PASS`, `FAIL`, or
  `NON_MESURÉ`. The exact denominator comes from runtime policy, never from the
  caller; missing or extra frames are rejected.
- Caller fact modality is only a hint. The runtime derives usable modality from
  signed authority `fact_verdicts` bound to fact SHA-512, evidence ID and evidence
  SHA-512; no unsigned `PROVEN` value can authorize a claim.
- Ed25519 receipts bind audience, expected policy, request SHA-512, request ID,
  reference time, trusted evaluation time, bounded validity window, nonce and the
  exact frame set.
- A replay ledger is mandatory. It uses a fixed filename inside an absolute,
  owner-only `0700` directory and validates file identity and the exact SQLite
  schema before every atomic nonce consumption.
- Every 00→05→05B node emits a SHA-512 receipt linked to the previous receipt;
  independent verification recomputes every node input and re-executes the full
  deterministic pipeline from the signed request.
- 05B copies the K3 conjunction; it cannot mint its own `PASS`.
- Runtime rendering requires a verified Ed25519 runtime envelope.
- Action verification requires trusted current time and rejects envelopes older
  than five minutes. Applications construct one `EnvelopeVerifier` at the trusted
  integration boundary and expose only its `verify`/`render_french` operations,
  never the verifier object itself. Its key stores and configuration are frozen.
  Untrusted calls cannot supply a historical time. Archival verification is
  deliberately not an action path. If arbitrary hostile Python executes in the
  same process, process isolation is mandatory; Python objects are not a sandbox.
- Frame/fact, calibration and runtime-signing trust stores are normalized to raw
  Ed25519 keys and rejected if any key material overlaps across roles.
- Promotion requires semantic `PASS` **and** a trusted, signed, bounded
  calibration whose measured score is strictly above both its signed threshold
  and the runtime floor `9`; the signed threshold itself cannot be below `9`.
- Caller-controlled floats, open schemas, free-text control fields, oversized
  trees and ambiguous unmeasured states fail closed.

## Reporting

Open a private security report with the repository owner. Include the affected
commit SHA, minimal reproducer, expected invariant, observed result and whether a
test key or production trust root was involved. Never publish private keys,
nonces from live environments or confidential facts.

## Explicit non-guarantees

Local tests do not establish deployment isolation, key custody, human
naturalness, scientific validity or an externally calibrated value of S.
