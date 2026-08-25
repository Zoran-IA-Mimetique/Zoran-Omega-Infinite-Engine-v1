"""Ed25519 authority, calibration and mandatory persistent anti-replay."""

from __future__ import annotations

import base64
import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .core import (
    FAIL, NON_MESURE, PASS, CoherenceError, canonical_json, clone_canonical,
    closed, parse_utc, sha512_value, validate_id, validate_sha512,
)

AUTHORITY_KEYS = {
    "_type", "version", "key_id", "policy_id", "audience", "nonce",
    "request_id", "request_sha512", "reference_time", "issued_at", "expires_at",
    "frame_verdicts", "fact_verdicts", "payload_sha512", "signature",
}
CALIBRATION_KEYS = {
    "_type", "version", "key_id", "calibration_id", "audience", "issued_at",
    "expires_at", "dataset_sha512", "variables", "units", "bounds",
    "threshold", "payload_sha512", "signature",
}
FRAME_NAMES = frozenset({
    "LOCAL", "LOWER", "PEER", "UPPER", "TEMPORAL", "USER", "PROOF",
    "SCIENCE", "SECURITY", "PRIVACY", "LAW", "RESOURCES", "ENERGY",
    "CLIMATE", "PLANETARY", "DOWNSTREAM", "MAINTENANCE", "ROLLBACK",
})
MAX_RECEIPT_LIFETIME = timedelta(minutes=15)
LEDGER_APPLICATION_ID = 0x5A4F5241
LEDGER_USER_VERSION = 1
LEDGER_SCHEMA = (
    (0, "key_id", "TEXT", 1, None, 1),
    (1, "nonce", "TEXT", 1, None, 2),
    (2, "request_sha512", "TEXT", 1, None, 0),
    (3, "consumed_at", "TEXT", 1, None, 0),
)
CREATE_LEDGER_SQL = (
    "CREATE TABLE consumed_nonces (key_id TEXT NOT NULL, nonce TEXT NOT NULL, "
    "request_sha512 TEXT NOT NULL, consumed_at TEXT NOT NULL, "
    "PRIMARY KEY(key_id, nonce)) WITHOUT ROWID"
)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: Any, code: str) -> bytes:
    if not isinstance(value, str) or len(value) > 256:
        raise CoherenceError(code)
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise CoherenceError(code) from exc


def _public(value: bytes | Ed25519PublicKey, code: str) -> Ed25519PublicKey:
    if isinstance(value, Ed25519PublicKey):
        return value
    try:
        return Ed25519PublicKey.from_public_bytes(value)
    except (TypeError, ValueError) as exc:
        raise CoherenceError(code) from exc


@dataclass(frozen=True)
class Ed25519Signer:
    key_id: str
    private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls, key_id: str) -> "Ed25519Signer":
        validate_id(key_id, "INVALID_KEY_ID")
        return cls(key_id=key_id, private_key=Ed25519PrivateKey.generate())

    @property
    def public_bytes(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    def sign_mapping(self, unsigned: Mapping[str, Any]) -> str:
        return _b64(self.private_key.sign(canonical_json(unsigned, maximum_bytes=4_194_304).encode("utf-8")))


class ReplayLedger:
    """Nonce ledger rooted in an owner-only directory with a fixed filename."""

    def __init__(self, storage_root: str | os.PathLike[str]) -> None:
        supplied = Path(storage_root)
        if not supplied.is_absolute():
            raise CoherenceError("REPLAY_LEDGER_ROOT_NOT_ABSOLUTE")
        if not supplied.exists() or supplied.is_symlink():
            raise CoherenceError("REPLAY_LEDGER_ROOT_UNSAFE")
        root_stat = supplied.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != os.getuid() or stat.S_IMODE(root_stat.st_mode) != 0o700:
            raise CoherenceError("REPLAY_LEDGER_ROOT_UNSAFE")
        self.root = supplied.resolve(strict=True)
        self.path = self.root / "replay.sqlite"
        existed = os.path.lexists(self.path)
        if existed:
            file_stat = self.path.lstat()
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != os.getuid() or file_stat.st_nlink != 1:
                raise CoherenceError("REPLAY_LEDGER_FILE_UNSAFE")
        else:
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
            os.close(descriptor)
        os.chmod(self.path, 0o600, follow_symlinks=False)
        self._identity = (self.path.lstat().st_dev, self.path.lstat().st_ino)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path), timeout=10, isolation_level=None, check_same_thread=False
        )
        self._connection.execute("PRAGMA journal_mode=DELETE")
        self._connection.execute("PRAGMA synchronous=FULL")
        if existed:
            self._validate_schema()
        else:
            self._connection.execute(f"PRAGMA application_id={LEDGER_APPLICATION_ID}")
            self._connection.execute(f"PRAGMA user_version={LEDGER_USER_VERSION}")
            self._connection.execute(CREATE_LEDGER_SQL)
            self._validate_schema()

    def _validate_identity(self) -> None:
        current = self.path.lstat()
        if not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid() or current.st_nlink != 1:
            raise CoherenceError("REPLAY_LEDGER_FILE_UNSAFE")
        if (current.st_dev, current.st_ino) != self._identity:
            raise CoherenceError("REPLAY_LEDGER_IDENTITY_CHANGED")

    def _validate_schema(self) -> None:
        application_id = self._connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        table = tuple(self._connection.execute("PRAGMA table_info(consumed_nonces)"))
        objects = tuple(self._connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ))
        if application_id != LEDGER_APPLICATION_ID or user_version != LEDGER_USER_VERSION:
            raise CoherenceError("REPLAY_LEDGER_IDENTITY_MISMATCH")
        if table != LEDGER_SCHEMA or objects != (("table", "consumed_nonces", "consumed_nonces", CREATE_LEDGER_SQL),):
            raise CoherenceError("REPLAY_LEDGER_SCHEMA_MISMATCH")

    def consume(self, *, key_id: str, nonce: str, request_sha512: str, consumed_at: str) -> None:
        validate_id(key_id, "INVALID_KEY_ID")
        validate_id(nonce, "INVALID_NONCE")
        validate_sha512(request_sha512, "INVALID_REQUEST_SHA512")
        parse_utc(consumed_at, "INVALID_CONSUMED_AT")
        with self._lock:
            self._validate_identity()
            self._validate_schema()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                cursor = self._connection.execute(
                    "INSERT INTO consumed_nonces VALUES (?, ?, ?, ?)",
                    (key_id, nonce, request_sha512, consumed_at),
                )
                stored = self._connection.execute(
                    "SELECT request_sha512, consumed_at FROM consumed_nonces WHERE key_id=? AND nonce=?",
                    (key_id, nonce),
                ).fetchone()
                if cursor.rowcount != 1 or stored != (request_sha512, consumed_at):
                    self._connection.execute("ROLLBACK")
                    raise CoherenceError("REPLAY_LEDGER_WRITE_NOT_DURABLE")
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._connection.execute("ROLLBACK")
                raise CoherenceError("AUTHORITY_NONCE_REPLAY") from exc


def _seal(unsigned: dict[str, Any], signer: Ed25519Signer) -> dict[str, Any]:
    payload_sha512 = sha512_value(unsigned)
    signed = {**unsigned, "payload_sha512": payload_sha512}
    return {**signed, "signature": signer.sign_mapping(signed)}


def build_authority_receipt(
    *, signer: Ed25519Signer, policy_id: str, audience: str, nonce: str,
    request: Mapping[str, Any], frame_verdicts: Mapping[str, str],
    fact_verdicts: Mapping[str, Mapping[str, str]],
    issued_at: str, expires_at: str,
) -> dict[str, Any]:
    clean_request = clone_canonical(request)
    request_id = validate_id(clean_request.get("request_id"), "INVALID_REQUEST_ID")
    reference_time = clean_request.get("reference_time")
    parse_utc(reference_time, "INVALID_REFERENCE_TIME")
    unsigned = {
        "_type": "zoran_frame_authority_receipt", "version": "ZORAN-FRAME-AUTHORITY-V1",
        "key_id": signer.key_id, "policy_id": validate_id(policy_id, "INVALID_POLICY_ID"),
        "audience": validate_id(audience, "INVALID_AUDIENCE"),
        "nonce": validate_id(nonce, "INVALID_NONCE"), "request_id": request_id,
        "request_sha512": sha512_value(clean_request), "reference_time": reference_time,
        "issued_at": issued_at, "expires_at": expires_at,
        "frame_verdicts": dict(sorted(frame_verdicts.items())),
        "fact_verdicts": {key: dict(value) for key, value in sorted(fact_verdicts.items())},
    }
    return _seal(unsigned, signer)


def _valid_window(issued_at: Any, expires_at: Any, reference_time: Any, evaluation_time: Any, prefix: str) -> None:
    issued = parse_utc(issued_at, f"INVALID_{prefix}_ISSUED_AT")
    expires = parse_utc(expires_at, f"INVALID_{prefix}_EXPIRES_AT")
    reference = parse_utc(reference_time, "INVALID_REFERENCE_TIME")
    evaluated = parse_utc(evaluation_time, "INVALID_EVALUATION_TIME")
    if expires <= issued or expires - issued > MAX_RECEIPT_LIFETIME:
        raise CoherenceError(f"{prefix}_VALIDITY_WINDOW_MISMATCH")
    if not (issued <= reference <= expires and issued <= evaluated <= expires):
        raise CoherenceError(f"{prefix}_VALIDITY_WINDOW_MISMATCH")


def verify_authority_receipt(
    receipt: Mapping[str, Any], *, request: Mapping[str, Any], required_frames: tuple[str, ...],
    trusted_keys: Mapping[str, bytes | Ed25519PublicKey], audience: str,
    expected_policy_id: str, evaluation_time: str, ledger: ReplayLedger | None = None,
    consume_nonce: bool = False,
) -> dict[str, Any]:
    clean = dict(closed(clone_canonical(receipt), AUTHORITY_KEYS, "AUTHORITY_SCHEMA_CLOSED"))
    clean_request = clone_canonical(request)
    if clean["_type"] != "zoran_frame_authority_receipt" or clean["version"] != "ZORAN-FRAME-AUTHORITY-V1":
        raise CoherenceError("AUTHORITY_VERSION_MISMATCH")
    unsigned = {key: clean[key] for key in clean if key not in {"payload_sha512", "signature"}}
    validate_sha512(clean["payload_sha512"], "INVALID_AUTHORITY_PAYLOAD_SHA512")
    if clean["payload_sha512"] != sha512_value(unsigned):
        raise CoherenceError("AUTHORITY_DIGEST_MISMATCH")
    key_id = validate_id(clean["key_id"], "INVALID_AUTHORITY_KEY_ID")
    if key_id not in trusted_keys:
        raise CoherenceError("UNTRUSTED_AUTHORITY_KEY")
    signed = {**unsigned, "payload_sha512": clean["payload_sha512"]}
    try:
        _public(trusted_keys[key_id], "INVALID_AUTHORITY_PUBLIC_KEY").verify(
            _unb64(clean["signature"], "INVALID_AUTHORITY_SIGNATURE"),
            canonical_json(signed).encode("utf-8"),
        )
    except InvalidSignature as exc:
        raise CoherenceError("INVALID_AUTHORITY_SIGNATURE") from exc
    if clean["audience"] != validate_id(audience, "INVALID_AUDIENCE"):
        raise CoherenceError("AUTHORITY_AUDIENCE_MISMATCH")
    if clean["policy_id"] != validate_id(expected_policy_id, "INVALID_EXPECTED_POLICY_ID"):
        raise CoherenceError("AUTHORITY_POLICY_MISMATCH")
    if clean["request_id"] != clean_request.get("request_id") or clean["request_sha512"] != sha512_value(clean_request):
        raise CoherenceError("AUTHORITY_REQUEST_BINDING_MISMATCH")
    if clean["reference_time"] != clean_request.get("reference_time"):
        raise CoherenceError("AUTHORITY_REFERENCE_TIME_MISMATCH")
    _valid_window(clean["issued_at"], clean["expires_at"], clean["reference_time"], evaluation_time, "AUTHORITY")
    frames = clean["frame_verdicts"]
    if not isinstance(frames, dict) or set(frames) != set(required_frames):
        raise CoherenceError("AUTHORITY_FRAME_COVERAGE_MISMATCH")
    if any(frame not in FRAME_NAMES or verdict not in {PASS, FAIL, NON_MESURE} for frame, verdict in frames.items()):
        raise CoherenceError("INVALID_FRAME_VERDICT")
    facts = clean_request.get("facts")
    verdicts = clean["fact_verdicts"]
    if not isinstance(facts, list) or not isinstance(verdicts, dict):
        raise CoherenceError("AUTHORITY_FACT_COVERAGE_MISMATCH")
    by_id = {fact.get("fact_id"): fact for fact in facts if isinstance(fact, dict)}
    if len(by_id) != len(facts) or set(verdicts) != set(by_id):
        raise CoherenceError("AUTHORITY_FACT_COVERAGE_MISMATCH")
    verified_facts = {}
    for fact_id, verdict in verdicts.items():
        validate_id(fact_id, "INVALID_FACT_ID")
        clean_verdict = closed(
            verdict, {"modality", "evidence_id", "evidence_sha512", "fact_sha512"},
            "FACT_VERDICT_SCHEMA_CLOSED",
        )
        if clean_verdict["modality"] not in {"PROVEN", "REPORTED", "UNKNOWN"}:
            raise CoherenceError("INVALID_FACT_VERDICT_MODALITY")
        if clean_verdict["evidence_id"] != by_id[fact_id].get("evidence_id"):
            raise CoherenceError("FACT_VERDICT_EVIDENCE_BINDING_MISMATCH")
        validate_id(clean_verdict["evidence_id"], "INVALID_EVIDENCE_ID")
        validate_sha512(clean_verdict["evidence_sha512"], "INVALID_EVIDENCE_SHA512")
        if clean_verdict["fact_sha512"] != sha512_value(by_id[fact_id]):
            raise CoherenceError("FACT_VERDICT_FACT_BINDING_MISMATCH")
        verified_facts[fact_id] = dict(clean_verdict)
    if consume_nonce:
        if not isinstance(ledger, ReplayLedger):
            raise CoherenceError("REPLAY_LEDGER_REQUIRED")
        ledger.consume(key_id=key_id, nonce=clean["nonce"], request_sha512=clean["request_sha512"], consumed_at=evaluation_time)
    return {
        "key_id": key_id, "policy_id": clean["policy_id"],
        "frame_verdicts": dict(sorted(frames.items())),
        "fact_verdicts": dict(sorted(verified_facts.items())), "receipt": clean,
    }


def build_calibration_receipt(
    *, signer: Ed25519Signer, calibration_id: str, audience: str,
    dataset_sha512: str, variables: Mapping[str, str], units: Mapping[str, str],
    bounds: Mapping[str, Mapping[str, str]], threshold: str,
    issued_at: str, expires_at: str,
) -> dict[str, Any]:
    unsigned = {
        "_type": "zoran_s_add_v2_calibration", "version": "ZORAN-S-ADD-V2-CALIBRATION-V1",
        "key_id": signer.key_id,
        "calibration_id": validate_id(calibration_id, "INVALID_CALIBRATION_ID"),
        "audience": validate_id(audience, "INVALID_AUDIENCE"), "issued_at": issued_at,
        "expires_at": expires_at,
        "dataset_sha512": validate_sha512(dataset_sha512, "INVALID_DATASET_SHA512"),
        "variables": dict(variables), "units": dict(units),
        "bounds": {key: dict(value) for key, value in bounds.items()}, "threshold": threshold,
    }
    return _seal(unsigned, signer)


def _decimal(value: Any, code: str) -> Decimal:
    if not isinstance(value, str):
        raise CoherenceError(code)
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CoherenceError(code) from exc
    if not result.is_finite():
        raise CoherenceError(code)
    return result


def verify_calibration_receipt(
    receipt: Mapping[str, Any] | None, *, trusted_keys: Mapping[str, bytes | Ed25519PublicKey],
    audience: str, reference_time: str, evaluation_time: str,
) -> dict[str, Any]:
    formula = "S_ADD_V2 = (β × ΔΦ)/(1 + T + σ)"
    if receipt is None:
        return {"formula": formula, "measurement": NON_MESURE, "certified_above_threshold": False, "reason": "SIGNED_CALIBRATION_MISSING"}
    clean = dict(closed(clone_canonical(receipt), CALIBRATION_KEYS, "CALIBRATION_SCHEMA_CLOSED"))
    unsigned = {key: clean[key] for key in clean if key not in {"payload_sha512", "signature"}}
    if clean["_type"] != "zoran_s_add_v2_calibration" or clean["version"] != "ZORAN-S-ADD-V2-CALIBRATION-V1":
        raise CoherenceError("CALIBRATION_VERSION_MISMATCH")
    validate_sha512(clean["payload_sha512"], "INVALID_CALIBRATION_PAYLOAD_SHA512")
    if clean["payload_sha512"] != sha512_value(unsigned):
        raise CoherenceError("CALIBRATION_DIGEST_MISMATCH")
    key_id = validate_id(clean["key_id"], "INVALID_CALIBRATION_KEY_ID")
    if key_id not in trusted_keys:
        raise CoherenceError("UNTRUSTED_CALIBRATION_KEY")
    signed = {**unsigned, "payload_sha512": clean["payload_sha512"]}
    try:
        _public(trusted_keys[key_id], "INVALID_CALIBRATION_PUBLIC_KEY").verify(
            _unb64(clean["signature"], "INVALID_CALIBRATION_SIGNATURE"),
            canonical_json(signed).encode("utf-8"),
        )
    except InvalidSignature as exc:
        raise CoherenceError("INVALID_CALIBRATION_SIGNATURE") from exc
    if clean["audience"] != validate_id(audience, "INVALID_AUDIENCE"):
        raise CoherenceError("CALIBRATION_AUDIENCE_MISMATCH")
    _valid_window(clean["issued_at"], clean["expires_at"], reference_time, evaluation_time, "CALIBRATION")
    names = {"beta", "delta_phi", "tension", "sigma"}
    if not all(isinstance(clean[name], dict) for name in ("variables", "units", "bounds")):
        raise CoherenceError("CALIBRATION_VARIABLE_COVERAGE_MISMATCH")
    if set(clean["variables"]) != names or set(clean["units"]) != names or set(clean["bounds"]) != names:
        raise CoherenceError("CALIBRATION_VARIABLE_COVERAGE_MISMATCH")
    values = {name: _decimal(clean["variables"][name], "INVALID_CALIBRATION_VALUE") for name in names}
    if values["tension"] < 0 or values["sigma"] < 0:
        raise CoherenceError("CALIBRATION_PHYSICAL_DOMAIN_MISMATCH")
    for name in names:
        bound = closed(clean["bounds"][name], {"minimum", "maximum"}, "CALIBRATION_BOUND_SCHEMA_CLOSED")
        minimum = _decimal(bound["minimum"], "INVALID_CALIBRATION_BOUND")
        maximum = _decimal(bound["maximum"], "INVALID_CALIBRATION_BOUND")
        if minimum > values[name] or values[name] > maximum:
            raise CoherenceError("CALIBRATION_VALUE_OUT_OF_BOUNDS")
        if not isinstance(clean["units"][name], str) or not clean["units"][name]:
            raise CoherenceError("CALIBRATION_UNIT_MISSING")
    threshold = _decimal(clean["threshold"], "INVALID_CALIBRATION_THRESHOLD")
    score = (values["beta"] * values["delta_phi"]) / (Decimal(1) + values["tension"] + values["sigma"])
    return {
        "formula": formula, "measurement": PASS, "score_decimal": format(score.normalize(), "f"),
        "threshold_decimal": format(threshold.normalize(), "f"),
        "certified_above_threshold": score > threshold,
        "calibration_id": validate_id(clean["calibration_id"], "INVALID_CALIBRATION_ID"),
        "dataset_sha512": validate_sha512(clean["dataset_sha512"], "INVALID_DATASET_SHA512"),
        "authority_key_id": key_id, "reason": "SIGNED_CALIBRATION_VERIFIED",
    }


def utc_window(reference_time: str, *, minutes: int = 5) -> tuple[str, str]:
    reference = parse_utc(reference_time, "INVALID_REFERENCE_TIME")
    if not isinstance(minutes, int) or not 1 <= minutes <= 14:
        raise CoherenceError("INVALID_WINDOW_MINUTES")
    return (
        (reference - timedelta(minutes=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        (reference + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
