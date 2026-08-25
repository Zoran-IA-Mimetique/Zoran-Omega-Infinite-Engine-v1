"""Closed types, bounded canonical JSON and strict K3 conjunction."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

PASS = "PASS"
FAIL = "FAIL"
NON_MESURE = "NON_MESURÉ"
K3_VALUES = frozenset({PASS, FAIL, NON_MESURE})
SHA512_RE = re.compile(r"^[0-9a-f]{128}$")
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,95}$")
DEFAULT_MAXIMUM_BYTES = 1_048_576
MAXIMUM_INTEGER_BITS = 2_048


class CoherenceError(ValueError):
    """Stable fail-closed error with a machine-readable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_tree(
    value: Any, *, maximum_bytes: int = DEFAULT_MAXIMUM_BYTES, depth: int = 0,
    state: dict[str, Any] | None = None,
) -> None:
    """Reject hostile JSON trees before serialization allocates their full size."""
    if not isinstance(maximum_bytes, int) or not 1 <= maximum_bytes <= 16_777_216:
        raise CoherenceError("INVALID_MAXIMUM_BYTES")
    if state is None:
        state = {"nodes": 0, "bytes": 0, "active": set()}
    state["nodes"] += 1
    if state["nodes"] > 20_000 or depth > 18:
        raise CoherenceError("JSON_TREE_OUT_OF_BOUNDS")

    def charge(amount: int) -> None:
        state["bytes"] += amount
        if state["bytes"] > maximum_bytes:
            raise CoherenceError("PAYLOAD_SIZE_OUT_OF_BOUNDS")

    if value is None:
        charge(4)
        return
    if type(value) is bool:
        charge(5)
        return
    if type(value) is int:
        if value.bit_length() > MAXIMUM_INTEGER_BITS:
            raise CoherenceError("JSON_INTEGER_OUT_OF_BOUNDS")
        remaining = maximum_bytes - state["bytes"]
        digits_upper_bound = ((value.bit_length() * 30_103) + 99_999) // 100_000 + 2
        if digits_upper_bound > remaining:
            raise CoherenceError("PAYLOAD_SIZE_OUT_OF_BOUNDS")
        try:
            charge(len(str(value)))
        except (ValueError, OverflowError) as exc:
            raise CoherenceError("JSON_INTEGER_OUT_OF_BOUNDS") from exc
        return
    if type(value) is str:
        if len(value) + 2 > maximum_bytes - state["bytes"]:
            raise CoherenceError("PAYLOAD_SIZE_OUT_OF_BOUNDS")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise CoherenceError("INVALID_UNICODE_SCALAR")
        try:
            charge(len(value.encode("utf-8")) + 2)
        except UnicodeEncodeError as exc:
            raise CoherenceError("INVALID_UNICODE_SCALAR") from exc
        return
    if isinstance(value, float):
        raise CoherenceError("FLOAT_FORBIDDEN_IN_SEALED_ARTIFACT")
    if type(value) not in {dict, list, tuple}:
        raise CoherenceError("NON_JSON_VALUE")
    identity = id(value)
    if identity in state["active"]:
        raise CoherenceError("CYCLIC_JSON_VALUE")
    state["active"].add(identity)
    try:
        if isinstance(value, dict):
            if len(value) > 2_048 or any(type(key) is not str for key in value):
                raise CoherenceError("JSON_OBJECT_OUT_OF_BOUNDS")
            charge(2 + max(0, len(value) - 1))
            for key in sorted(value):
                if len(key) + 3 > maximum_bytes - state["bytes"]:
                    raise CoherenceError("PAYLOAD_SIZE_OUT_OF_BOUNDS")
                if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                    raise CoherenceError("INVALID_UNICODE_SCALAR")
                try:
                    charge(len(key.encode("utf-8")) + 3)
                except UnicodeEncodeError as exc:
                    raise CoherenceError("INVALID_UNICODE_SCALAR") from exc
                _validate_tree(value[key], maximum_bytes=maximum_bytes, depth=depth + 1, state=state)
            return
        if len(value) > 4_096:
            raise CoherenceError("JSON_SEQUENCE_OUT_OF_BOUNDS")
        charge(2 + max(0, len(value) - 1))
        for item in value:
            _validate_tree(item, maximum_bytes=maximum_bytes, depth=depth + 1, state=state)
    finally:
        state["active"].remove(identity)


def canonical_json(value: Any, *, maximum_bytes: int = DEFAULT_MAXIMUM_BYTES) -> str:
    _validate_tree(value, maximum_bytes=maximum_bytes)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (UnicodeEncodeError, ValueError, OverflowError, RecursionError) as exc:
        raise CoherenceError("JSON_SERIALIZATION_REJECTED") from exc


def clone_canonical(value: Any, *, maximum_bytes: int = DEFAULT_MAXIMUM_BYTES) -> Any:
    encoded = canonical_json(value, maximum_bytes=maximum_bytes).encode("utf-8")
    if len(encoded) > maximum_bytes:
        raise CoherenceError("PAYLOAD_SIZE_OUT_OF_BOUNDS")
    return json.loads(encoded.decode("utf-8"))


def sha512_value(value: Any, *, maximum_bytes: int = DEFAULT_MAXIMUM_BYTES) -> str:
    return hashlib.sha512(canonical_json(value, maximum_bytes=maximum_bytes).encode("utf-8")).hexdigest()


def sha512_bytes(value: bytes) -> str:
    return hashlib.sha512(value).hexdigest()


def closed(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CoherenceError(code)
    return value


def validate_id(value: Any, code: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise CoherenceError(code)
    return value


def validate_sha512(value: Any, code: str) -> str:
    if not isinstance(value, str) or SHA512_RE.fullmatch(value) is None:
        raise CoherenceError(code)
    return value


def parse_utc(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CoherenceError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CoherenceError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CoherenceError(code)
    return parsed


def utc_text(value: datetime, code: str = "INVALID_EVALUATION_TIME") -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise CoherenceError(code)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_text(value: Any, *, maximum: int, code: str) -> str:
    if not isinstance(value, str):
        raise CoherenceError(code)
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    if not text or len(text) > maximum or any(ord(char) < 32 for char in text):
        raise CoherenceError(code)
    return text


def validate_lexeme(value: Any, code: str) -> str:
    text = normalize_text(value, maximum=160, code=code)
    if any(not (char.isalnum() or char in " -'’") for char in text):
        raise CoherenceError(code)
    return text


def k3_and(values: Iterable[str]) -> str:
    states = tuple(values)
    if not states or any(state not in K3_VALUES for state in states):
        raise CoherenceError("INVALID_K3_CONJUNCTION")
    if FAIL in states:
        return FAIL
    if NON_MESURE in states:
        return NON_MESURE
    return PASS
