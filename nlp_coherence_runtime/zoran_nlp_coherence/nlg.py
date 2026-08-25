"""Closed French surface realizer for verified semantic claims."""

from __future__ import annotations

from typing import Any, Mapping

from .core import (
    FAIL, NON_MESURE, PASS, CoherenceError, closed, sha512_value, validate_id,
    validate_lexeme, validate_sha512,
)

CLAIM_KEYS = {"claim_id", "subject", "predicate", "object", "polarity", "evidence_id", "evidence_sha512"}


def _sentence(claim: Mapping[str, Any]) -> str:
    clean = closed(claim, CLAIM_KEYS, "CLAIM_SCHEMA_CLOSED")
    validate_id(clean["claim_id"], "INVALID_CLAIM_ID")
    validate_id(clean["evidence_id"], "INVALID_EVIDENCE_ID")
    validate_sha512(clean["evidence_sha512"], "INVALID_EVIDENCE_SHA512")
    subject = validate_lexeme(clean["subject"], "INVALID_CLAIM_SUBJECT")
    obj = validate_lexeme(clean["object"], "INVALID_CLAIM_OBJECT")
    if clean["polarity"] not in {"POSITIVE", "NEGATIVE"}:
        raise CoherenceError("INVALID_CLAIM_POLARITY")
    negative = clean["polarity"] == "NEGATIVE"
    predicate = clean["predicate"]
    if predicate == "status":
        return f"Le statut de {subject} n’est pas {obj}." if negative else f"Le statut de {subject} est {obj}."
    if predicate == "contains":
        return f"{subject} ne contient pas {obj}." if negative else f"{subject} contient {obj}."
    if predicate == "causes":
        return f"{subject} ne provoque pas {obj}." if negative else f"{subject} provoque {obj}."
    if predicate == "supports":
        return f"{subject} ne soutient pas {obj}." if negative else f"{subject} soutient {obj}."
    if predicate == "is":
        return f"{subject} n’est pas {obj}." if negative else f"{subject} est {obj}."
    raise CoherenceError("UNSUPPORTED_CLAIM_PREDICATE")


def realize_french(*, status: str, claims: list[Mapping[str, Any]], goal: str, envelope_sha512: str) -> dict[str, Any]:
    validate_sha512(envelope_sha512, "INVALID_ENVELOPE_SHA512")
    if goal not in {"ANSWER", "EXPLAIN", "COMPARE"}:
        raise CoherenceError("INVALID_SURFACE_GOAL")
    if not isinstance(claims, list):
        raise CoherenceError("INVALID_SURFACE_CLAIMS")
    if status == FAIL:
        text = "Je ne peux pas répondre : les éléments vérifiés sont contradictoires ou un cadre obligatoire a échoué."
        kind = "BLOCKING_REFUSAL"
    elif status == NON_MESURE:
        text = "Je ne peux pas conclure avec les preuves disponibles. Il manque au moins un élément mesuré ou autorisé."
        kind = "MEASUREMENT_REFUSAL"
    elif status == PASS:
        if not claims:
            raise CoherenceError("PASS_WITHOUT_CLAIM")
        sentences = [_sentence(claim) for claim in claims]
        prefix = "D’après les éléments vérifiés, "
        first = sentences[0]
        text = prefix + first[0].lower() + first[1:]
        if len(sentences) > 1:
            text += " En complément, " + " ".join(sentences[1:])
        if goal == "EXPLAIN":
            text += " Cette réponse reprend uniquement les faits prouvés et autorisés."
        kind = "VERIFIED_ANSWER"
    else:
        raise CoherenceError("INVALID_SURFACE_STATUS")
    unsigned = {"locale": "fr-FR", "status": status, "kind": kind, "text": text, "envelope_sha512": envelope_sha512}
    return {**unsigned, "surface_sha512": sha512_value(unsigned)}
