"""Structured bounded proof and independently verifiable SHA-512 seal."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import cryptography
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .authority import Ed25519Signer, ReplayLedger, build_authority_receipt, utc_window
from .core import NON_MESURE, PASS, canonical_json, sha512_bytes
from .runtime import EnvelopeVerifier, NlpCoherenceRuntime

REFERENCE_TIME = "2026-08-25T12:00:00Z"
EVALUATION_TIME = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
FRAMES = ["LOCAL", "PROOF", "SECURITY", "USER"]
EXPECTED_TESTS = 46
SECURITY_REVIEW = Path("evidence/SECURITY_REVIEW_V1.json")
SECURITY_REVIEW_PUBLIC_KEY_B64 = "BGsGGBsHJtfK0N4OuVd4O0k4fTemn6qBsusX3xjA/vc="


def _signer(key_id: str, offset: int) -> Ed25519Signer:
    raw = bytes(((index + offset) % 256 for index in range(1, 33)))
    return Ed25519Signer(key_id, Ed25519PrivateKey.from_private_bytes(raw))


def _request(index: int, modality: str = "PROVEN") -> dict:
    return {
        "request_id": f"REQ-PROOF-{index:04d}", "reference_time": REFERENCE_TIME,
        "locale": "fr-FR", "utterance": f"Quel est le statut de Brique {index} ?",
        "response_goal": "ANSWER",
        "facts": [{"fact_id": f"FACT-PROOF-{index:04d}", "subject": f"Brique {index}",
                   "predicate": "status", "object": "prête", "polarity": "POSITIVE",
                   "modality": modality, "evidence_id": f"EVIDENCE-PROOF-{index:04d}"}],
        "required_frames": list(FRAMES), "calibration": None,
    }


def _authority(signer: Ed25519Signer, value: dict, nonce: str) -> dict:
    issued, expires = utc_window(REFERENCE_TIME)
    verdicts = {
        fact["fact_id"]: {
            "modality": fact["modality"], "evidence_id": fact["evidence_id"],
            "evidence_sha512": hashlib.sha512(("PROOF-EVIDENCE:" + fact["evidence_id"]).encode()).hexdigest(),
            "fact_sha512": hashlib.sha512(canonical_json(fact).encode()).hexdigest(),
        }
        for fact in value["facts"]
    }
    return build_authority_receipt(
        signer=signer, policy_id="POLICY-PROOF-V1", audience="ZORAN-NLP-PROOF",
        nonce=nonce, request=value, frame_verdicts={frame: PASS for frame in FRAMES},
        fact_verdicts=verdicts,
        issued_at=issued, expires_at=expires,
    )


class _StructuredResult(unittest.TestResult):
    def addFailure(self, test, err):
        super().addFailure(test, err)

    def addError(self, test, err):
        super().addError(test, err)


def _run_suite(root: Path) -> dict:
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py", top_level_dir=str(root))
    identities: list[str] = []

    def collect(node):
        for item in node:
            if isinstance(item, unittest.TestSuite):
                collect(item)
            else:
                identities.append(item.id())

    collect(suite)
    result = _StructuredResult()
    suite.run(result)
    return {
        "runner": "unittest-in-process-structured", "tests": result.testsRun,
        "test_identity_sha512": hashlib.sha512(canonical_json(sorted(identities)).encode("utf-8")).hexdigest(),
        "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "ok": result.wasSuccessful() and result.testsRun == len(identities),
    }


def _secure_directory(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)
    return path


def _bounded_trials() -> dict:
    authority = _signer("AUTH-PROOF-V1", 0)
    runtime_signer = _signer("RUNTIME-PROOF-V1", 64)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve(); os.chmod(root, 0o700)
        engine = NlpCoherenceRuntime(
            audience="ZORAN-NLP-PROOF", expected_policy_id="POLICY-PROOF-V1",
            mandatory_frames=tuple(FRAMES),
            trusted_authorities={authority.key_id: authority.public_bytes}, trusted_calibrators={},
            runtime_signer=runtime_signer, replay_ledger=ReplayLedger(_secure_directory(root, "ledger")),
            clock=lambda: EVALUATION_TIME,
        )
        trust = {"verifier": EnvelopeVerifier(
            trusted_runtime_signers={runtime_signer.key_id: runtime_signer.public_bytes},
            trusted_authorities={authority.key_id: authority.public_bytes},
            trusted_calibrators={}, audience="ZORAN-NLP-PROOF",
            expected_policy_id="POLICY-PROOF-V1", mandatory_frames=tuple(FRAMES),
            clock=lambda: EVALUATION_TIME,
        )}
        value = _request(1)
        baseline = engine.execute(value, authority_receipt=_authority(authority, value, "NONCE-BASELINE-1"))
        baseline_serialized = canonical_json(baseline, maximum_bytes=4_194_304)
        verification_matches = sum(
            canonical_json(trust["verifier"].verify(baseline), maximum_bytes=4_194_304) == baseline_serialized
            for _ in range(1_000)
        )
        pickup = []
        for index in range(1, 51):
            expected = PASS if index <= 25 else NON_MESURE
            candidate = _request(index + 100, "PROVEN" if index <= 25 else "UNKNOWN")
            observed = trust["verifier"].verify(
                engine.execute(candidate, authority_receipt=_authority(authority, candidate, f"NONCE-{index:04d}"))
            )["status"]
            pickup.append({"request_id": candidate["request_id"], "expected": expected, "observed": observed,
                           "status": PASS if observed == expected else "FAIL"})
        return {
            "deterministic_verification": {"passed": verification_matches, "total": 1_000,
                                           "baseline_sha512": baseline["runtime_sha512"]},
            "pickup_50": {"passed": sum(item["status"] == PASS for item in pickup), "total": 50,
                          "population_sha512": hashlib.sha512(canonical_json(pickup).encode("utf-8")).hexdigest()},
        }


def _files(root: Path) -> list[Path]:
    ignored = {"SHA512SUMS", "PROOF_MANIFEST.json"}
    return sorted(path for path in root.rglob("*") if path.is_file()
                  and path.name not in ignored and "__pycache__" not in path.parts
                  and ".pytest_cache" not in path.parts
                  and not path.name.endswith((".pyc", ".sqlite", ".sqlite-journal")))


def _security_source_files(root: Path) -> list[Path]:
    return [
        path for path in _files(root)
        if path.relative_to(root) != SECURITY_REVIEW
        and "security_scan" not in path.relative_to(root).parts
        and "artifacts" not in path.relative_to(root).parts
    ]


def security_source_digest(root: Path) -> tuple[str, int]:
    hashes = {str(path.relative_to(root)): sha512_bytes(path.read_bytes()) for path in _security_source_files(root)}
    return hashlib.sha512(canonical_json(hashes).encode("utf-8")).hexdigest(), len(hashes)


def verify_security_review(root: Path) -> dict:
    path = root / SECURITY_REVIEW
    if not path.is_file() or path.is_symlink():
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_MISSING"}
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_INVALID_JSON"}
    expected_keys = {
        "schema", "reviewer", "scope", "source_set_sha512", "reviewed_files",
        "finding_counts", "prior_validated_findings_closed", "residual_findings",
        "limitations", "verdict", "review_sha512", "review_signature",
    }
    if not isinstance(review, dict) or set(review) != expected_keys:
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_SCHEMA"}
    unsigned = {key: review[key] for key in review if key not in {"review_sha512", "review_signature"}}
    if review["review_sha512"] != hashlib.sha512(canonical_json(unsigned).encode("utf-8")).hexdigest():
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_DIGEST"}
    signed = {**unsigned, "review_sha512": review["review_sha512"]}
    try:
        signature = base64.b64decode(review["review_signature"], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(SECURITY_REVIEW_PUBLIC_KEY_B64, validate=True))
        public_key.verify(signature, canonical_json(signed).encode("utf-8"))
    except (ValueError, TypeError, InvalidSignature):
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_SIGNATURE"}
    if review.get("reviewer") != "CODEX-SECURITY-REVIEWER-V1":
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_IDENTITY"}
    source_digest, source_count = security_source_digest(root)
    counts = review.get("finding_counts")
    expected_count_keys = {"critical", "high", "medium", "low", "informational"}
    if review.get("source_set_sha512") != source_digest or review.get("reviewed_files") != source_count:
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_SOURCE_DRIFT"}
    if not isinstance(counts, dict) or set(counts) != expected_count_keys or any(value != 0 for value in counts.values()):
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_FINDINGS_OPEN"}
    if review.get("verdict") != PASS or review.get("residual_findings") != []:
        return {"verdict": "FAIL", "reason": "SECURITY_REVIEW_NOT_PASS"}
    return {"verdict": PASS, "reason": "BOUND_SECURITY_REVIEW_VERIFIED",
            "source_set_sha512": source_digest, "review_sha512": review["review_sha512"]}


def verify_committed_seal(root: Path) -> dict:
    sums_path = root / "SHA512SUMS"
    if not sums_path.is_file():
        return {"verdict": "FAIL", "reason": "SHA512SUMS_MISSING", "checked": 0}
    seen = set(); checked = 0
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return {"verdict": "FAIL", "reason": "SHA512SUMS_FORMAT", "checked": checked}
        expected, relative = line.split("  ", 1)
        path = Path(relative)
        if len(expected) != 128 or any(char not in "0123456789abcdef" for char in expected):
            return {"verdict": "FAIL", "reason": "SHA512SUMS_DIGEST", "checked": checked}
        if path.is_absolute() or ".." in path.parts or relative in seen:
            return {"verdict": "FAIL", "reason": "SHA512SUMS_PATH", "checked": checked}
        unresolved = root / path
        if unresolved.is_symlink():
            return {"verdict": "FAIL", "reason": "SHA512SUMS_SYMLINK", "checked": checked}
        candidate = unresolved.resolve()
        if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
            return {"verdict": "FAIL", "reason": "SHA512SUMS_TARGET", "checked": checked}
        if sha512_bytes(candidate.read_bytes()) != expected:
            return {"verdict": "FAIL", "reason": "SHA512SUMS_MISMATCH", "file": relative, "checked": checked}
        seen.add(relative); checked += 1
    expected_paths = {str(path.relative_to(root)) for path in _files(root)}
    expected_paths.add("artifacts/PROOF_MANIFEST.json")
    if seen != expected_paths:
        return {"verdict": "FAIL", "reason": "SHA512SUMS_INCOMPLETE", "checked": checked,
                "missing": sorted(expected_paths - seen), "unexpected": sorted(seen - expected_paths)}
    return {"verdict": PASS, "reason": "COMMITTED_SEAL_VERIFIED", "checked": checked}


def generate(root: Path) -> dict:
    output = root / "artifacts"
    output.mkdir(exist_ok=True)
    first = _run_suite(root); second = _run_suite(root); trials = _bounded_trials()
    security_review = verify_security_review(root)
    source_hashes = {str(path.relative_to(root)): sha512_bytes(path.read_bytes()) for path in _files(root)}
    all_pass = first["ok"] and second["ok"] and first["tests"] == second["tests"] == EXPECTED_TESTS
    all_pass = all_pass and first["test_identity_sha512"] == second["test_identity_sha512"]
    all_pass = all_pass and trials["deterministic_verification"]["passed"] == 1_000 and trials["pickup_50"]["passed"] == 50
    all_pass = all_pass and security_review["verdict"] == PASS
    manifest = {
        "schema": "ZORAN-NLP-COHERENCE-PROOF-V1", "bounded_verdict": PASS if all_pass else "FAIL",
        "classification": "CLOS_THÉORIQUE_UTILISABLE" if all_pass else "FAIL",
        "test_denominator": {"passed": EXPECTED_TESTS if all_pass else min(first["tests"], second["tests"]),
                             "total": EXPECTED_TESTS, "runs": [first, second]},
        **trials,
        "security_review": security_review,
        "s_add_v2": {"formula": "S_ADD_V2 = (β × ΔΦ)/(1 + T + σ)", "measurement": NON_MESURE,
                     "reason": "NO_TRUSTED_EXTERNAL_CALIBRATION_IN_REPOSITORY"},
        "external_validation": NON_MESURE, "promotion_allowed": False,
        "source_sha512": source_hashes,
        "environment": {"python": platform.python_version(), "cryptography": cryptography.__version__},
        "open_debt": ["EXTERNAL_S_CALIBRATION", "QUALIFIED_HUMAN_NATURALNESS", "PRODUCTION_KEY_CUSTODY", "PLANETARY_EFFECT"],
    }
    proof_path = output / "PROOF_MANIFEST.json"
    proof_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    files = _files(root) + [proof_path]
    sums = "".join(f"{sha512_bytes(path.read_bytes())}  {path.relative_to(root)}\n" for path in sorted(set(files)))
    (root / "SHA512SUMS").write_text(sums, encoding="utf-8")
    return {
        "verdict": manifest["bounded_verdict"], "tests": manifest["test_denominator"],
        "pickup": manifest["pickup_50"], "verification": manifest["deterministic_verification"],
        "proof_sha512": sha512_bytes(proof_path.read_bytes()),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-seal-only", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    result = verify_committed_seal(root) if args.verify_seal_only else generate(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
