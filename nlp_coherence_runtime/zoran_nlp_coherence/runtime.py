"""Single fail-closed NLP authority and independently verifiable envelope."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .authority import (
    Ed25519Signer, ReplayLedger, _public, _unb64, verify_authority_receipt,
    verify_calibration_receipt,
)
from .core import (
    NON_MESURE, PASS, CoherenceError, canonical_json, clone_canonical, closed,
    parse_utc, sha512_value, utc_text, validate_id, validate_sha512,
)
from .nlg import realize_french
from .pipeline import REQUEST_KEYS, run_pipeline, verify_receipt_chain

RUNTIME_KEYS = {
    "_type", "version", "runtime_id", "audience", "policy_id", "evaluated_at",
    "request", "authority_receipt", "request_id", "reference_time", "request_sha512",
    "authority_key_id", "required_frames", "pipeline", "status", "s_add_v2",
    "promotion_threshold_decimal", "promotion_allowed", "runtime_signer_key_id",
    "runtime_sha512", "runtime_signature",
}


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


def _promotion(status: str, calibration: Mapping[str, Any], required_threshold: Decimal) -> bool:
    if status != PASS or calibration.get("measurement") != PASS:
        return False
    score = _decimal(calibration.get("score_decimal"), "INVALID_S_SCORE")
    signed_threshold = _decimal(calibration.get("threshold_decimal"), "INVALID_S_THRESHOLD")
    return calibration.get("certified_above_threshold") is True and signed_threshold >= required_threshold and score > required_threshold


def _normalized_trust_store(
    values: Mapping[str, bytes | Ed25519PublicKey], code: str,
) -> dict[str, bytes]:
    normalized = {}
    for key_id, value in values.items():
        validate_id(key_id, code)
        normalized[key_id] = _public(value, code).public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    return normalized


def _reject_role_overlap(*stores: Mapping[str, bytes]) -> None:
    material_sets = [set(store.values()) for store in stores]
    for index, left in enumerate(material_sets):
        for right in material_sets[index + 1:]:
            if left & right:
                raise CoherenceError("AUTHORITY_ROLE_KEY_OVERLAP")


class NlpCoherenceRuntime:
    """Only supported authority for NLP semantic decisions and rendering."""

    VERSION = "ZORAN-NLP-COHERENCE-RUNTIME-V1"

    def __init__(
        self, *, audience: str, expected_policy_id: str,
        mandatory_frames: tuple[str, ...],
        trusted_authorities: Mapping[str, bytes | Ed25519PublicKey],
        trusted_calibrators: Mapping[str, bytes | Ed25519PublicKey],
        runtime_signer: Ed25519Signer, replay_ledger: ReplayLedger,
        clock: Callable[[], datetime] | None = None, required_promotion_threshold: str = "9",
    ) -> None:
        self.audience = validate_id(audience, "INVALID_AUDIENCE")
        self.expected_policy_id = validate_id(expected_policy_id, "INVALID_EXPECTED_POLICY_ID")
        if not mandatory_frames or tuple(sorted(set(mandatory_frames))) != mandatory_frames:
            raise CoherenceError("MANDATORY_FRAMES_NOT_CANONICAL")
        self.mandatory_frames = mandatory_frames
        if not isinstance(replay_ledger, ReplayLedger):
            raise CoherenceError("REPLAY_LEDGER_REQUIRED")
        self.trusted_authorities = _normalized_trust_store(trusted_authorities, "INVALID_AUTHORITY_PUBLIC_KEY")
        self.trusted_calibrators = _normalized_trust_store(trusted_calibrators, "INVALID_CALIBRATION_PUBLIC_KEY")
        self.runtime_signer = runtime_signer
        runtime_material = {runtime_signer.key_id: runtime_signer.public_bytes}
        _reject_role_overlap(self.trusted_authorities, self.trusted_calibrators, runtime_material)
        self.replay_ledger = replay_ledger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.required_promotion_threshold = _decimal(required_promotion_threshold, "INVALID_REQUIRED_PROMOTION_THRESHOLD")
        if self.required_promotion_threshold < Decimal("9"):
            raise CoherenceError("PROMOTION_THRESHOLD_BELOW_NINE")

    def execute(self, request: Mapping[str, Any], *, authority_receipt: Mapping[str, Any]) -> dict[str, Any]:
        clean = clone_canonical(request)
        closed(clean, REQUEST_KEYS, "NLP_REQUEST_SCHEMA_CLOSED")
        required = clean["required_frames"]
        if not isinstance(required, list):
            raise CoherenceError("REQUIRED_FRAMES_NOT_SEQUENCE")
        if required != list(self.mandatory_frames):
            raise CoherenceError("POLICY_MANDATORY_FRAME_MISMATCH")
        evaluated_at = utc_text(self.clock())
        authority = verify_authority_receipt(
            authority_receipt, request=clean, required_frames=tuple(required),
            trusted_keys=self.trusted_authorities, audience=self.audience,
            expected_policy_id=self.expected_policy_id, evaluation_time=evaluated_at,
            ledger=self.replay_ledger, consume_nonce=True,
        )
        pipeline = run_pipeline(clean, authority["frame_verdicts"], authority["fact_verdicts"])
        calibration = verify_calibration_receipt(
            clean["calibration"], trusted_keys=self.trusted_calibrators,
            audience=self.audience, reference_time=clean["reference_time"],
            evaluation_time=evaluated_at,
        )
        promotion = _promotion(pipeline["status"], calibration, self.required_promotion_threshold)
        unsigned = {
            "_type": "zoran_nlp_runtime_envelope", "version": self.VERSION,
            "runtime_id": "RUNTIME-" + sha512_value({"request": clean, "chain": pipeline["chain_head_sha512"], "evaluated_at": evaluated_at})[:24].upper(),
            "audience": self.audience, "policy_id": self.expected_policy_id,
            "evaluated_at": evaluated_at, "request": clean, "authority_receipt": authority["receipt"],
            "request_id": clean["request_id"], "reference_time": clean["reference_time"],
            "request_sha512": sha512_value(clean), "authority_key_id": authority["key_id"],
            "required_frames": required, "pipeline": pipeline, "status": pipeline["status"],
            "s_add_v2": calibration,
            "promotion_threshold_decimal": format(self.required_promotion_threshold.normalize(), "f"),
            "promotion_allowed": promotion, "runtime_signer_key_id": self.runtime_signer.key_id,
        }
        digest = sha512_value(unsigned, maximum_bytes=4_194_304)
        signed = {**unsigned, "runtime_sha512": digest}
        return {**signed, "runtime_signature": self.runtime_signer.sign_mapping(signed)}


def _verify_envelope_at(
    envelope: Mapping[str, Any], *, trusted_runtime_signers: Mapping[str, bytes | Ed25519PublicKey],
    trusted_authorities: Mapping[str, bytes | Ed25519PublicKey],
    trusted_calibrators: Mapping[str, bytes | Ed25519PublicKey], audience: str,
    expected_policy_id: str, mandatory_frames: tuple[str, ...], verification_time: str,
    required_promotion_threshold: str = "9",
) -> dict[str, Any]:
    clean = dict(closed(clone_canonical(envelope, maximum_bytes=4_194_304), RUNTIME_KEYS, "RUNTIME_ENVELOPE_SCHEMA_CLOSED"))
    if clean["_type"] != "zoran_nlp_runtime_envelope" or clean["version"] != NlpCoherenceRuntime.VERSION:
        raise CoherenceError("RUNTIME_VERSION_MISMATCH")
    unsigned = {key: clean[key] for key in clean if key not in {"runtime_sha512", "runtime_signature"}}
    validate_sha512(clean["runtime_sha512"], "INVALID_RUNTIME_SHA512")
    if clean["runtime_sha512"] != sha512_value(unsigned, maximum_bytes=4_194_304):
        raise CoherenceError("RUNTIME_DIGEST_MISMATCH")
    key_id = validate_id(clean["runtime_signer_key_id"], "INVALID_RUNTIME_SIGNER_KEY_ID")
    if key_id not in trusted_runtime_signers:
        raise CoherenceError("UNTRUSTED_RUNTIME_SIGNER")
    signed = {**unsigned, "runtime_sha512": clean["runtime_sha512"]}
    try:
        _public(trusted_runtime_signers[key_id], "INVALID_RUNTIME_PUBLIC_KEY").verify(
            _unb64(clean["runtime_signature"], "INVALID_RUNTIME_SIGNATURE"),
            canonical_json(signed, maximum_bytes=4_194_304).encode("utf-8"),
        )
    except InvalidSignature as exc:
        raise CoherenceError("INVALID_RUNTIME_SIGNATURE") from exc
    if clean["audience"] != validate_id(audience, "INVALID_AUDIENCE"):
        raise CoherenceError("RUNTIME_AUDIENCE_MISMATCH")
    if clean["policy_id"] != validate_id(expected_policy_id, "INVALID_EXPECTED_POLICY_ID"):
        raise CoherenceError("RUNTIME_POLICY_MISMATCH")
    verified_now = parse_utc(verification_time, "INVALID_VERIFICATION_TIME")
    evaluated = parse_utc(clean["evaluated_at"], "INVALID_EVALUATION_TIME")
    if verified_now < evaluated - timedelta(minutes=1) or verified_now > evaluated + timedelta(minutes=5):
        raise CoherenceError("RUNTIME_ENVELOPE_EXPIRED")
    request = clone_canonical(clean["request"])
    closed(request, REQUEST_KEYS, "NLP_REQUEST_SCHEMA_CLOSED")
    if clean["request_id"] != request["request_id"] or clean["reference_time"] != request["reference_time"] or clean["request_sha512"] != sha512_value(request):
        raise CoherenceError("RUNTIME_REQUEST_BINDING_MISMATCH")
    authority = verify_authority_receipt(
        clean["authority_receipt"], request=request, required_frames=tuple(request["required_frames"]),
        trusted_keys=trusted_authorities, audience=audience, expected_policy_id=expected_policy_id,
        evaluation_time=verification_time, consume_nonce=False,
    )
    if tuple(sorted(set(mandatory_frames))) != mandatory_frames or request["required_frames"] != list(mandatory_frames):
        raise CoherenceError("POLICY_MANDATORY_FRAME_MISMATCH")
    if clean["authority_key_id"] != authority["key_id"] or clean["required_frames"] != request["required_frames"]:
        raise CoherenceError("RUNTIME_AUTHORITY_BINDING_MISMATCH")
    expected_pipeline = run_pipeline(request, authority["frame_verdicts"], authority["fact_verdicts"])
    if clean["pipeline"] != expected_pipeline:
        raise CoherenceError("RUNTIME_PIPELINE_REEXECUTION_MISMATCH")
    chain = verify_receipt_chain(
        clean["pipeline"]["node_receipts"], clean["pipeline"]["node_outputs"],
        request, authority["fact_verdicts"],
    )
    if chain != clean["pipeline"]["chain_head_sha512"] or clean["pipeline"]["status"] != clean["status"] or clean["pipeline"]["claims"] != clean["pipeline"]["node_outputs"][6]["claims"]:
        raise CoherenceError("RUNTIME_PIPELINE_BINDING_MISMATCH")
    expected_calibration = verify_calibration_receipt(
        request["calibration"], trusted_keys=trusted_calibrators, audience=audience,
        reference_time=request["reference_time"], evaluation_time=verification_time,
    )
    if clean["s_add_v2"] != expected_calibration:
        raise CoherenceError("RUNTIME_CALIBRATION_BINDING_MISMATCH")
    required = _decimal(required_promotion_threshold, "INVALID_REQUIRED_PROMOTION_THRESHOLD")
    if required < Decimal("9") or clean["promotion_threshold_decimal"] != format(required.normalize(), "f"):
        raise CoherenceError("RUNTIME_PROMOTION_THRESHOLD_MISMATCH")
    if clean["promotion_allowed"] is not _promotion(clean["status"], expected_calibration, required):
        raise CoherenceError("RUNTIME_PROMOTION_BINDING_MISMATCH")
    return clone_canonical(clean, maximum_bytes=4_194_304)


class EnvelopeVerifier:
    """Trusted action verifier; current time is obtained from configured clock only."""

    __slots__ = (
        "_trusted_runtime_signers", "_trusted_authorities", "_trusted_calibrators",
        "_audience", "_expected_policy_id", "_mandatory_frames", "_clock",
        "_required_promotion_threshold", "_frozen",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("ENVELOPE_VERIFIER_CONFIGURATION_FROZEN")
        object.__setattr__(self, name, value)

    def __init__(
        self, *, trusted_runtime_signers: Mapping[str, bytes | Ed25519PublicKey],
        trusted_authorities: Mapping[str, bytes | Ed25519PublicKey],
        trusted_calibrators: Mapping[str, bytes | Ed25519PublicKey], audience: str,
        expected_policy_id: str, mandatory_frames: tuple[str, ...],
        clock: Callable[[], datetime] | None = None, required_promotion_threshold: str = "9",
    ) -> None:
        self._trusted_runtime_signers = MappingProxyType(_normalized_trust_store(trusted_runtime_signers, "INVALID_RUNTIME_PUBLIC_KEY"))
        self._trusted_authorities = MappingProxyType(_normalized_trust_store(trusted_authorities, "INVALID_AUTHORITY_PUBLIC_KEY"))
        self._trusted_calibrators = MappingProxyType(_normalized_trust_store(trusted_calibrators, "INVALID_CALIBRATION_PUBLIC_KEY"))
        _reject_role_overlap(self._trusted_runtime_signers, self._trusted_authorities, self._trusted_calibrators)
        self._audience = validate_id(audience, "INVALID_AUDIENCE")
        self._expected_policy_id = validate_id(expected_policy_id, "INVALID_EXPECTED_POLICY_ID")
        if not mandatory_frames or tuple(sorted(set(mandatory_frames))) != mandatory_frames:
            raise CoherenceError("MANDATORY_FRAMES_NOT_CANONICAL")
        self._mandatory_frames = mandatory_frames
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._required_promotion_threshold = required_promotion_threshold
        if _decimal(required_promotion_threshold, "INVALID_REQUIRED_PROMOTION_THRESHOLD") < Decimal("9"):
            raise CoherenceError("PROMOTION_THRESHOLD_BELOW_NINE")
        self._frozen = True

    def verify(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        return _verify_envelope_at(
            envelope, trusted_runtime_signers=self._trusted_runtime_signers,
            trusted_authorities=self._trusted_authorities,
            trusted_calibrators=self._trusted_calibrators, audience=self._audience,
            expected_policy_id=self._expected_policy_id, mandatory_frames=self._mandatory_frames,
            verification_time=utc_text(self._clock()),
            required_promotion_threshold=self._required_promotion_threshold,
        )

    def render_french(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        clean = self.verify(envelope)
        return realize_french(
            status=clean["status"], claims=clean["pipeline"]["claims"],
            goal=clean["request"]["response_goal"], envelope_sha512=clean["runtime_sha512"],
        )
