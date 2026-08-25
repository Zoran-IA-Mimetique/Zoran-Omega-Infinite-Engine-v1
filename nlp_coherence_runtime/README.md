# Zoran NLP Coherence Runtime v1

This component closes the four P0 seams identified by the formal NLP audit:

1. no default frame verdict;
2. a real, receipt-bound `00→05` pipeline;
3. a `05B` commit gate that cannot self-approve;
4. one authoritative runtime and one verified French renderer.

It also adds separate Ed25519 calibration authority, persistent nonce replay
protection, closed schemas, SHA-512 node receipts and a reproducible proof kit.

## Exact guarantee

The local bounded claim is `CLOS_THÉORIQUE_UTILISABLE` only when all of the
following pass on the exact commit:

- 46/46 closed unit/integration/adversarial tests, executed twice from structured results;
- 50/50 distinct frozen pick-up cases;
- 1,000/1,000 byte-identical independent verifications of one consumed receipt;
- 100% of files listed in `SHA512SUMS` verify;
- zero residual finding in the signed scoped review.

This is 100% of a declared finite denominator. It is not a claim of general NLP
coverage, scientific validation, production readiness or human-level naturalness.

## S gate

The only accepted formula is:

`S_ADD_V2 = (β × ΔΦ)/(1 + T + σ)`

Without a previously trusted external calibration authority, dataset SHA-512,
units, bounds, validity window and Ed25519 signature, the mandatory result is:

`S_ADD_V2 = (β × ΔΦ)/(1 + T + σ) = NON_MESURÉ`

The test suite contains a clearly labelled synthetic test calibration with
`S=100 > 9` solely to prove that the cryptographic gate works. It is not a real
certificate and cannot be loaded by production unless its test key is explicitly
misconfigured as trusted.

## Run offline

```bash
python -m unittest discover -s tests -v
python -m zoran_nlp_coherence.proof
sha512sum -c SHA512SUMS
```

To build without an unpinned PEP 517 bootstrap, first install
`build-requirements-lock.txt` with `--require-hashes --only-binary=:all:`, then
run `pip wheel . --no-build-isolation --no-deps`.

## Runtime sequence

| Node | Real input | Output | Failure rule |
|---|---|---|---|
| 00 | complete request | normalized closed request | reject open/oversized input |
| 01 | normalized request | intent and subject discovery | ambiguity → `NON_MESURÉ` |
| 02 | discovered target | exact required frame names | verdicts stay external |
| 03 | normalized facts | closed fact plan | contradiction → `FAIL` |
| 04 | fact plan | evidence-bound claims | missing proof → `NON_MESURÉ` |
| 05 | signed frames + claims | strict K3 conjunction | `FAIL` dominates, then unknown |
| 05B | verified 05 receipt | commit or refusal | cannot create its own status |

## Integration rule

Do not import historical engines into this package. An application integrates one
`NlpCoherenceRuntime` instance, configures public-key trust stores outside source
control, provides an owner-only absolute `0700` replay-ledger directory and renders
only after the envelope is independently re-executed and verified. The certified CI
baseline is CPython 3.12 on GitHub's x86-64 Ubuntu runner; all dependency artifacts
and Actions are immutably pinned. The workflow is mirrored inside this component
so it belongs to `SHA512SUMS`; CI requires byte equality with the active repository
workflow before running any Python code.
