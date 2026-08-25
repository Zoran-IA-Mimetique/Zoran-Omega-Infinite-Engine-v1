"""Deterministic, causally verified 00→05→05B NLP pipeline."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .authority import FRAME_NAMES
from .core import (
    FAIL, NON_MESURE, PASS, CoherenceError, clone_canonical, closed, k3_and,
    normalize_text, parse_utc, sha512_value, validate_id, validate_lexeme,
    validate_sha512,
)

REQUEST_KEYS = {
    "request_id", "reference_time", "locale", "utterance", "response_goal",
    "facts", "required_frames", "calibration",
}
FACT_KEYS = {"fact_id", "subject", "predicate", "object", "polarity", "modality", "evidence_id"}
ALLOWED_PREDICATES = frozenset({"status", "contains", "causes", "supports", "is"})
ALLOWED_MODALITIES = frozenset({"PROVEN", "REPORTED", "UNKNOWN"})
ALLOWED_GOALS = frozenset({"ANSWER", "EXPLAIN", "COMPARE"})
NODE_IDS = ("00_NORMALIZE", "01_DISCOVER", "02_SELECT_FRAMES", "03_PLAN", "04_CANON", "05_COHERENCE", "05B_COMMIT")
RECEIPT_KEYS = {"node_id", "sequence", "input_sha512", "output_sha512", "status", "previous_sha512", "receipt_sha512"}
PREDICATE_CUES = {
    "status": ("statut",), "contains": ("contient", "contenir"),
    "causes": ("cause", "provoque"), "supports": ("soutient", "supporte"),
    "is": ("est",),
}


def _receipt(node_id: str, sequence: int, input_value: Any, output: Mapping[str, Any], previous: str) -> dict[str, Any]:
    unsigned = {
        "node_id": node_id, "sequence": sequence, "input_sha512": sha512_value(input_value),
        "output_sha512": sha512_value(output), "status": output["status"], "previous_sha512": previous,
    }
    return {**unsigned, "receipt_sha512": sha512_value(unsigned)}


def _expected_inputs(request: Mapping[str, Any], outputs: list[Mapping[str, Any]], fact_verdicts: Mapping[str, Any]) -> list[Any]:
    return [
        {"request": request, "fact_verdicts": fact_verdicts},
        outputs[0],
        outputs[1],
        {"previous": outputs[2], "normalized": outputs[0], "discovered": outputs[1]},
        outputs[3],
        {"previous": outputs[4], "frame_verdicts": outputs[2]["frame_verdicts"]},
        outputs[5],
    ]


def verify_receipt_chain(
    receipts: list[Mapping[str, Any]], node_outputs: list[Mapping[str, Any]],
    request: Mapping[str, Any], fact_verdicts: Mapping[str, Any],
) -> str:
    clean_receipts = clone_canonical(receipts, maximum_bytes=2_097_152)
    clean_outputs = clone_canonical(node_outputs, maximum_bytes=2_097_152)
    clean_request = clone_canonical(request)
    clean_fact_verdicts = clone_canonical(fact_verdicts)
    if len(clean_receipts) != len(NODE_IDS) or len(clean_outputs) != len(NODE_IDS):
        raise CoherenceError("NODE_CHAIN_LENGTH_MISMATCH")
    expected_inputs = _expected_inputs(clean_request, clean_outputs, clean_fact_verdicts)
    previous = "0" * 128
    for index, (receipt, output, expected_input) in enumerate(zip(clean_receipts, clean_outputs, expected_inputs)):
        clean = dict(closed(receipt, RECEIPT_KEYS, "NODE_RECEIPT_SCHEMA_CLOSED"))
        if clean["node_id"] != NODE_IDS[index] or clean["sequence"] != index or clean["previous_sha512"] != previous:
            raise CoherenceError("NODE_RECEIPT_CHAIN_MISMATCH")
        unsigned = {key: clean[key] for key in clean if key != "receipt_sha512"}
        if clean["receipt_sha512"] != sha512_value(unsigned) or clean["output_sha512"] != sha512_value(output):
            raise CoherenceError("NODE_RECEIPT_DIGEST_MISMATCH")
        if clean["input_sha512"] != sha512_value(expected_input):
            raise CoherenceError("NODE_RECEIPT_INPUT_BINDING_MISMATCH")
        if clean["status"] != output.get("status"):
            raise CoherenceError("NODE_RECEIPT_STATUS_MISMATCH")
        previous = clean["receipt_sha512"]
    coherence, commit = clean_outputs[5], clean_outputs[6]
    expected_status = k3_and([coherence["frame_conjunction"], coherence["node_conjunction"]])
    if coherence["status"] != expected_status or commit["status"] != expected_status:
        raise CoherenceError("05B_STATUS_INHERITANCE_MISMATCH")
    if commit.get("committed") is not (expected_status == PASS):
        raise CoherenceError("05B_COMMIT_BINDING_MISMATCH")
    expected_claims = clean_outputs[4].get("claims", []) if expected_status == PASS else []
    if commit.get("claims") != expected_claims:
        raise CoherenceError("05B_CLAIM_BINDING_MISMATCH")
    return previous


def _normalize_request(raw: Mapping[str, Any], fact_verdicts: Mapping[str, Any]) -> dict[str, Any]:
    clean = clone_canonical(raw)
    closed(clean, REQUEST_KEYS, "NLP_REQUEST_SCHEMA_CLOSED")
    request_id = validate_id(clean["request_id"], "INVALID_REQUEST_ID")
    parse_utc(clean["reference_time"], "INVALID_REFERENCE_TIME")
    if clean["locale"] != "fr-FR" or clean["response_goal"] not in ALLOWED_GOALS:
        raise CoherenceError("UNSUPPORTED_LANGUAGE_OR_GOAL")
    utterance = normalize_text(clean["utterance"], maximum=4_096, code="INVALID_UTTERANCE")
    required = clean["required_frames"]
    if not isinstance(required, list) or not required or required != sorted(set(required)):
        raise CoherenceError("REQUIRED_FRAMES_NOT_CANONICAL")
    if any(frame not in FRAME_NAMES for frame in required):
        raise CoherenceError("INVALID_REQUIRED_FRAME")
    facts = clean["facts"]
    if not isinstance(facts, list) or not facts or len(facts) > 128:
        raise CoherenceError("FACT_COUNT_OUT_OF_BOUNDS")
    normalized_facts = []
    seen = set()
    for raw_fact in facts:
        fact = dict(closed(raw_fact, FACT_KEYS, "FACT_SCHEMA_CLOSED"))
        fact_id = validate_id(fact["fact_id"], "INVALID_FACT_ID")
        if fact_id in seen:
            raise CoherenceError("DUPLICATE_FACT_ID")
        seen.add(fact_id)
        if fact["predicate"] not in ALLOWED_PREDICATES or fact["polarity"] not in {"POSITIVE", "NEGATIVE"} or fact["modality"] not in ALLOWED_MODALITIES:
            raise CoherenceError("INVALID_FACT_SEMANTICS")
        verdict = fact_verdicts.get(fact_id) if isinstance(fact_verdicts, Mapping) else None
        if not isinstance(verdict, Mapping) or verdict.get("modality") not in ALLOWED_MODALITIES:
            raise CoherenceError("VERIFIED_FACT_VERDICT_MISSING")
        closed(verdict, {"modality", "evidence_id", "evidence_sha512", "fact_sha512"}, "FACT_VERDICT_SCHEMA_CLOSED")
        if verdict["evidence_id"] != fact["evidence_id"] or verdict["fact_sha512"] != sha512_value(raw_fact):
            raise CoherenceError("FACT_VERDICT_BINDING_MISMATCH")
        validate_sha512(verdict["evidence_sha512"], "INVALID_EVIDENCE_SHA512")
        normalized_facts.append({
            "fact_id": fact_id, "subject": validate_lexeme(fact["subject"], "INVALID_FACT_SUBJECT"),
            "predicate": fact["predicate"], "object": validate_lexeme(fact["object"], "INVALID_FACT_OBJECT"),
            "polarity": fact["polarity"], "modality": verdict["modality"],
            "evidence_id": validate_id(fact["evidence_id"], "INVALID_EVIDENCE_ID"),
            "evidence_sha512": verdict["evidence_sha512"],
        })
    if not isinstance(fact_verdicts, Mapping) or set(fact_verdicts) != seen:
        raise CoherenceError("AUTHORITY_FACT_COVERAGE_MISMATCH")
    if clean["calibration"] is not None and not isinstance(clean["calibration"], dict):
        raise CoherenceError("INVALID_CALIBRATION_ARTIFACT")
    return {
        "status": PASS, "request_id": request_id, "reference_time": clean["reference_time"],
        "locale": "fr-FR", "utterance": utterance, "response_goal": clean["response_goal"],
        "facts": normalized_facts, "required_frames": required, "calibration": clean["calibration"],
    }


def _has_word(text: str, cue: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(cue) + r"(?!\w)", text, flags=re.IGNORECASE) is not None


def _discover(normalized: Mapping[str, Any]) -> dict[str, Any]:
    utterance = normalized["utterance"].casefold()
    if any(_has_word(utterance, cue) for cue in ("pourquoi", "explique", "expliquer", "comment")):
        intent = "EXPLAIN"
    elif any(_has_word(utterance, cue) for cue in ("compare", "comparer", "différence", "versus")):
        intent = "COMPARE"
    elif any(_has_word(utterance, cue) for cue in ("quel", "quelle", "quels", "quelles")):
        intent = "ANSWER"
    else:
        intent = NON_MESURE
    subjects = sorted({
        fact["subject"] for fact in normalized["facts"]
        if _has_word(utterance, fact["subject"].casefold())
    })
    predicates = sorted({predicate for predicate, cues in PREDICATE_CUES.items() if any(_has_word(utterance, cue) for cue in cues)})
    if len(predicates) > 1 and "is" in predicates:
        predicates.remove("is")
    target_ok = intent == normalized["response_goal"] and len(subjects) == 1 and len(predicates) == 1
    return {
        "status": PASS if target_ok else NON_MESURE, "intent": intent,
        "target": {"subject": subjects[0] if len(subjects) == 1 else None,
                   "predicate": predicates[0] if len(predicates) == 1 else None},
        "reason": "EXACT_SEMANTIC_TARGET" if target_ok else "SEMANTIC_TARGET_UNRESOLVED",
    }


def _select_frames(normalized: Mapping[str, Any], discovered: Mapping[str, Any], frame_verdicts: Mapping[str, str]) -> dict[str, Any]:
    clean_frames = clone_canonical(frame_verdicts)
    if not isinstance(clean_frames, dict) or set(clean_frames) != set(normalized["required_frames"]):
        raise CoherenceError("AUTHORITY_FRAME_COVERAGE_MISMATCH")
    if any(value not in {PASS, FAIL, NON_MESURE} for value in clean_frames.values()):
        raise CoherenceError("INVALID_FRAME_VERDICT")
    return {
        "status": discovered["status"], "required_frames": normalized["required_frames"],
        "authority_assignment": "EXTERNAL_VERIFIED_ONLY", "frame_verdicts": dict(sorted(clean_frames.items())),
    }


def _plan(normalized: Mapping[str, Any], discovered: Mapping[str, Any]) -> dict[str, Any]:
    if discovered["status"] != PASS:
        return {"status": NON_MESURE, "candidate_fact_ids": [], "reason": "SEMANTIC_TARGET_UNRESOLVED"}
    target = discovered["target"]
    candidates = [fact for fact in normalized["facts"] if fact["subject"] == target["subject"] and fact["predicate"] == target["predicate"]]
    polarities: dict[str, set[str]] = {}
    for fact in candidates:
        polarities.setdefault(fact["object"], set()).add(fact["polarity"])
    if any(len(values) > 1 for values in polarities.values()):
        return {"status": FAIL, "candidate_fact_ids": [], "reason": "CONTRADICTORY_FACTS"}
    proven = sorted((fact for fact in candidates if fact["modality"] == "PROVEN"), key=lambda fact: fact["fact_id"])
    needed = 2 if normalized["response_goal"] == "COMPARE" else 1
    if len(proven) < needed:
        reason = "COMPARISON_FACT_MISSING" if needed == 2 else "PROVEN_TARGET_FACT_MISSING"
        return {"status": NON_MESURE, "candidate_fact_ids": [], "reason": reason}
    selected = proven if needed == 2 else proven[:1]
    return {"status": PASS, "candidate_fact_ids": [fact["fact_id"] for fact in selected], "reason": "EXACT_TARGET_FACT_PLAN"}


def _canon(normalized: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan["status"] != PASS:
        return {"status": plan["status"], "claims": [], "reason": plan["reason"]}
    by_id = {fact["fact_id"]: fact for fact in normalized["facts"]}
    claims = []
    for fact_id in plan["candidate_fact_ids"]:
        fact = by_id[fact_id]
        claims.append({
            "claim_id": "CLAIM-" + sha512_value(fact)[:24].upper(), "subject": fact["subject"],
            "predicate": fact["predicate"], "object": fact["object"], "polarity": fact["polarity"],
            "evidence_id": fact["evidence_id"], "evidence_sha512": fact["evidence_sha512"],
        })
    return {"status": PASS, "claims": claims, "reason": "CLAIMS_DERIVED_FROM_EXACT_PROVEN_TARGET"}


def run_pipeline(
    request: Mapping[str, Any], frame_verdicts: Mapping[str, str],
    fact_verdicts: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    previous = "0" * 128

    normalized = _normalize_request(request, fact_verdicts)
    outputs.append(normalized)
    receipts.append(_receipt(NODE_IDS[0], 0, {"request": request, "fact_verdicts": fact_verdicts}, normalized, previous)); previous = receipts[-1]["receipt_sha512"]
    discovered = _discover(normalized)
    outputs.append(discovered)
    receipts.append(_receipt(NODE_IDS[1], 1, normalized, discovered, previous)); previous = receipts[-1]["receipt_sha512"]
    selected = _select_frames(normalized, discovered, frame_verdicts)
    outputs.append(selected)
    receipts.append(_receipt(NODE_IDS[2], 2, discovered, selected, previous)); previous = receipts[-1]["receipt_sha512"]
    plan_input = {"previous": selected, "normalized": normalized, "discovered": discovered}
    plan = _plan(normalized, discovered)
    outputs.append(plan)
    receipts.append(_receipt(NODE_IDS[3], 3, plan_input, plan, previous)); previous = receipts[-1]["receipt_sha512"]
    canon = _canon(normalized, plan)
    outputs.append(canon)
    receipts.append(_receipt(NODE_IDS[4], 4, plan, canon, previous)); previous = receipts[-1]["receipt_sha512"]
    frame_status = k3_and(selected["frame_verdicts"].values())
    node_status = k3_and([discovered["status"], selected["status"], plan["status"], canon["status"]])
    status = k3_and([frame_status, node_status])
    coherence = {"status": status, "frame_conjunction": frame_status, "node_conjunction": node_status, "rule": "FAIL_DOMINATES_THEN_NON_MESURE_THEN_PASS"}
    outputs.append(coherence)
    receipts.append(_receipt(NODE_IDS[5], 5, {"previous": canon, "frame_verdicts": selected["frame_verdicts"]}, coherence, previous)); previous = receipts[-1]["receipt_sha512"]
    commit = {"status": status, "committed": status == PASS, "claims": canon["claims"] if status == PASS else [], "reason": "VERIFIED_CHAIN_COMMITTED" if status == PASS else "K3_VETO_BLOCKED_COMMIT"}
    outputs.append(commit)
    receipts.append(_receipt(NODE_IDS[6], 6, coherence, commit, previous))
    chain_head = verify_receipt_chain(receipts, outputs, request, fact_verdicts)
    return {"status": status, "node_outputs": outputs, "node_receipts": receipts, "chain_head_sha512": chain_head, "claims": commit["claims"]}
