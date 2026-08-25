# Security Review: Zoran NLP Coherence Runtime v1

## Scope

The scan reviewed the canonical include paths and exclusions listed below.

- Scan mode: repository
- Target kind: directory_snapshot
- Target ID: zoran-nlp-coherence-runtime-v1
- Snapshot digest: codex-security-snapshot/v1:sha256:7fda11caa0f22962a2786947eb1c3050369c8e37868ed181e9472df1fb2b032a
- Inventory strategy: repository
- Included paths: .
- Excluded paths: artifacts/, security_scan/, evidence/SECURITY_REVIEW_V1.json, SHA512SUMS
- Runtime or test status: not recorded

Limitations and exclusions:
- Excluded artifacts/: Generated only after source review; cryptographically sealed by SHA512SUMS.
- Excluded security_scan/: Canonical scan output, not executable input to the reviewed runtime.
- Excluded evidence/SECURITY_REVIEW_V1.json: Generated signed projection of this completed review.
- Excluded SHA512SUMS: Generated only after all proof artifacts are final.

### Scan Summary

| Field | Value |
| --- | --- |
| Reportable findings | 0 |
| Severity mix | none |
| Confidence mix | none |
| Coverage | complete |
| Validation mode | not recorded |

Canonical artifacts: `scan-manifest.json`, `findings.json`, and `coverage.json`. This report is a deterministic projection of those files.

## Threat Model

No explicit canonical threat-model summary was recorded.

## Findings

### No findings

No reportable findings survived the canonical discovery, validation, and reportability gates.

## Reviewed Surfaces

| Surface | Risk Area | Outcome | Notes |
| --- | --- | --- | --- |
| Canonical JSON, scalar bounds and hostile trees | not recorded | No issue found | No additional canonical notes were recorded. |
| Ed25519 authority receipts and exact policy binding | not recorded | No issue found | No additional canonical notes were recorded. |
| SQLite replay ledger confinement and concurrency | not recorded | No issue found | No additional canonical notes were recorded. |
| Causal 00 to 05B receipt chain and re-execution | not recorded | No issue found | No additional canonical notes were recorded. |
| Goal, subject, predicate and evidence binding | not recorded | No issue found | No additional canonical notes were recorded. |
| Closed French realization and injection resistance | not recorded | No issue found | No additional canonical notes were recorded. |
| Runtime envelope signing, freshness and immutable verifier | not recorded | No issue found | No additional canonical notes were recorded. |
| Independent signed S calibration and threshold floor | not recorded | No issue found | No additional canonical notes were recorded. |
| Structured bounded proof and complete SHA-512 seal | not recorded | No issue found | No additional canonical notes were recorded. |
| Hash-locked dependencies and pinned CI actions | not recorded | No issue found | No additional canonical notes were recorded. |
