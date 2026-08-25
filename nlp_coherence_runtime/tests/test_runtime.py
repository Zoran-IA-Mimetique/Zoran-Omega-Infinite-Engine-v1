from __future__ import annotations

import copy
import hashlib
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from zoran_nlp_coherence import (
    CoherenceError, Ed25519Signer, NlpCoherenceRuntime, ReplayLedger,
    build_authority_receipt, build_calibration_receipt,
)
from zoran_nlp_coherence.authority import utc_window, verify_authority_receipt, verify_calibration_receipt
from zoran_nlp_coherence.core import FAIL, NON_MESURE, PASS, sha512_value
from zoran_nlp_coherence.pipeline import NODE_IDS, run_pipeline, verify_receipt_chain
from zoran_nlp_coherence.runtime import EnvelopeVerifier

REFERENCE_TIME = "2026-08-25T12:00:00Z"
EVALUATION_TIME = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
FRAMES = ["LOCAL", "PROOF", "SECURITY", "USER"]


def verify_envelope(envelope, *, verifier):
    return verifier.verify(envelope)


def render_verified_french(envelope, *, verifier):
    return verifier.render_french(envelope)


def request(index=1, *, modality="PROVEN", predicate="status", calibration=None, goal="ANSWER"):
    return {
        "request_id": f"REQ-{index:04d}", "reference_time": REFERENCE_TIME,
        "locale": "fr-FR", "utterance": f"Quel est le statut de Brique {index} ?",
        "response_goal": goal,
        "facts": [{
            "fact_id": f"FACT-{index:04d}", "subject": f"Brique {index}",
            "predicate": predicate, "object": "prête", "polarity": "POSITIVE",
            "modality": modality, "evidence_id": f"EVIDENCE-{index:04d}",
        }],
        "required_frames": list(FRAMES), "calibration": calibration,
    }


def fact_verdicts(value, modality_override=None):
    return {
        fact["fact_id"]: {
            "modality": modality_override or fact["modality"], "evidence_id": fact["evidence_id"],
            "evidence_sha512": hashlib.sha512(("TEST-EVIDENCE:" + fact["evidence_id"]).encode()).hexdigest(),
            "fact_sha512": sha512_value(fact),
        }
        for fact in value["facts"]
    }


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        os.chmod(self.root, 0o700)
        self.keys = {
            "authority": Ed25519Signer.generate("AUTH-TEST-1"),
            "calibrator": Ed25519Signer.generate("CAL-TEST-1"),
            "runtime": Ed25519Signer.generate("RUNTIME-TEST-1"),
        }

    def tearDown(self):
        self.temp.cleanup()

    def secure_dir(self, name):
        path = self.root / name
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        return path

    def ledger(self, name="ledger"):
        return ReplayLedger(self.secure_dir(name))

    def authority(self, value, *, nonce="NONCE-0001", verdict=PASS, signer=None, frames=None, policy="POLICY-TEST-1", fact_modality=None):
        issued, expires = utc_window(value["reference_time"])
        names = frames if frames is not None else value["required_frames"]
        return build_authority_receipt(
            signer=signer or self.keys["authority"], policy_id=policy,
            audience="ZORAN-NLP-TEST", nonce=nonce, request=value,
            frame_verdicts={frame: verdict for frame in names}, issued_at=issued, expires_at=expires,
            fact_verdicts=fact_verdicts(value, fact_modality),
        )

    def calibration(self, *, beta="100", threshold="9"):
        issued, expires = utc_window(REFERENCE_TIME)
        values = {"beta": beta, "delta_phi": "1", "tension": "0", "sigma": "0"}
        return build_calibration_receipt(
            signer=self.keys["calibrator"], calibration_id="CALIBRATION-TEST-1",
            audience="ZORAN-NLP-TEST", dataset_sha512=hashlib.sha512(b"frozen-test-dataset").hexdigest(),
            variables=values, units={name: "dimensionless-test-proxy" for name in values},
            bounds={name: {"minimum": "0", "maximum": "100"} for name in values},
            threshold=threshold, issued_at=issued, expires_at=expires,
        )

    def runtime(self, name="runtime-ledger", **overrides):
        values = dict(
            audience="ZORAN-NLP-TEST", expected_policy_id="POLICY-TEST-1",
            mandatory_frames=tuple(FRAMES),
            trusted_authorities={self.keys["authority"].key_id: self.keys["authority"].public_bytes},
            trusted_calibrators={self.keys["calibrator"].key_id: self.keys["calibrator"].public_bytes},
            runtime_signer=self.keys["runtime"], replay_ledger=self.ledger(name),
            clock=lambda: EVALUATION_TIME, required_promotion_threshold="9",
        )
        values.update(overrides)
        return NlpCoherenceRuntime(**values)

    def trust(self, verification_time=REFERENCE_TIME, threshold="9"):
        clock_value = datetime.fromisoformat(verification_time.replace("Z", "+00:00"))
        return {"verifier": EnvelopeVerifier(
            trusted_runtime_signers={self.keys["runtime"].key_id: self.keys["runtime"].public_bytes},
            trusted_authorities={self.keys["authority"].key_id: self.keys["authority"].public_bytes},
            trusted_calibrators={self.keys["calibrator"].key_id: self.keys["calibrator"].public_bytes},
            audience="ZORAN-NLP-TEST", expected_policy_id="POLICY-TEST-1",
            mandatory_frames=tuple(FRAMES), clock=lambda: clock_value,
            required_promotion_threshold=threshold,
        )}

    def auth_verify(self, receipt, value, **overrides):
        values = dict(
            receipt=receipt, request=value, required_frames=tuple(FRAMES),
            trusted_keys={self.keys["authority"].key_id: self.keys["authority"].public_bytes},
            audience="ZORAN-NLP-TEST", expected_policy_id="POLICY-TEST-1",
            evaluation_time=REFERENCE_TIME,
        )
        values.update(overrides)
        return verify_authority_receipt(**values)

    def execute(self, value, *, name="execute", verdict=PASS, nonce="NONCE-0001"):
        envelope = self.runtime(name).execute(value, authority_receipt=self.authority(value, verdict=verdict, nonce=nonce))
        return envelope, self.trust()

    def test_01_signed_authority_exact_coverage(self):
        value = request()
        observed = self.auth_verify(self.authority(value), value, ledger=self.ledger("authority"), consume_nonce=True)
        self.assertEqual(observed["frame_verdicts"], {frame: PASS for frame in FRAMES})

    def test_02_authority_full_request_binding(self):
        for field in ("request_id", "utterance", "response_goal"):
            value = request(); receipt = self.authority(value); hostile = copy.deepcopy(value)
            hostile[field] = "REQ-9999" if field == "request_id" else "altération"
            with self.subTest(field=field), self.assertRaisesRegex(CoherenceError, "AUTHORITY_REQUEST_BINDING_MISMATCH"):
                self.auth_verify(receipt, hostile)

    def test_03_missing_frame_never_defaults_to_pass(self):
        value = request()
        with self.assertRaisesRegex(CoherenceError, "AUTHORITY_FRAME_COVERAGE_MISMATCH"):
            self.auth_verify(self.authority(value, frames=FRAMES[:-1]), value)

    def test_04_signature_tamper_and_untrusted_key(self):
        value = request(); receipt = self.authority(value)
        hostile = copy.deepcopy(receipt); hostile["signature"] = "A" * len(hostile["signature"])
        with self.assertRaisesRegex(CoherenceError, "INVALID_AUTHORITY_SIGNATURE"):
            self.auth_verify(hostile, value)
        other = Ed25519Signer.generate("OTHER-KEY")
        with self.assertRaisesRegex(CoherenceError, "UNTRUSTED_AUTHORITY_KEY"):
            self.auth_verify(receipt, value, trusted_keys={other.key_id: other.public_bytes})

    def test_05_nonce_replay_persists(self):
        value = request(); receipt = self.authority(value); ledger = self.ledger("replay")
        self.auth_verify(receipt, value, ledger=ledger, consume_nonce=True)
        with self.assertRaisesRegex(CoherenceError, "AUTHORITY_NONCE_REPLAY"):
            self.auth_verify(receipt, value, ledger=ReplayLedger(ledger.root), consume_nonce=True)

    def test_06_missing_calibration_non_measured(self):
        result = verify_calibration_receipt(
            None, trusted_keys={}, audience="ZORAN-NLP-TEST", reference_time=REFERENCE_TIME,
            evaluation_time=REFERENCE_TIME,
        )
        self.assertEqual(result["measurement"], NON_MESURE)
        self.assertFalse(result["certified_above_threshold"])

    def test_07_signed_test_calibration_mechanics_above_nine(self):
        result = verify_calibration_receipt(
            self.calibration(), trusted_keys={self.keys["calibrator"].key_id: self.keys["calibrator"].public_bytes},
            audience="ZORAN-NLP-TEST", reference_time=REFERENCE_TIME, evaluation_time=REFERENCE_TIME,
        )
        self.assertEqual(result["score_decimal"], "100")
        self.assertTrue(result["certified_above_threshold"])

    def test_08_calibration_tamper_rejected(self):
        receipt = self.calibration(); receipt["variables"]["beta"] = "99"
        with self.assertRaisesRegex(CoherenceError, "CALIBRATION_DIGEST_MISMATCH"):
            verify_calibration_receipt(
                receipt, trusted_keys={self.keys["calibrator"].key_id: self.keys["calibrator"].public_bytes},
                audience="ZORAN-NLP-TEST", reference_time=REFERENCE_TIME, evaluation_time=REFERENCE_TIME,
            )

    def test_09_real_00_to_05b_chain(self):
        value = request(); result = run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))
        self.assertEqual(result["status"], PASS)
        self.assertEqual([item["node_id"] for item in result["node_receipts"]], list(NODE_IDS))
        self.assertTrue(result["node_outputs"][-1]["committed"])
        self.assertEqual(verify_receipt_chain(result["node_receipts"], result["node_outputs"], value, fact_verdicts(value)), result["chain_head_sha512"])

    def test_10_k3_veto_non_compensatory(self):
        for status in (FAIL, NON_MESURE):
            frames = {frame: PASS for frame in FRAMES}; frames["SECURITY"] = status
            value = request(); result = run_pipeline(value, frames, fact_verdicts(value))
            with self.subTest(status=status):
                self.assertEqual(result["status"], status); self.assertFalse(result["node_outputs"][-1]["committed"]); self.assertEqual(result["claims"], [])

    def test_11_unknown_intent_and_fact_non_measured(self):
        value = request(modality="UNKNOWN"); value["utterance"] = "Bonjour Brique 1"
        self.assertEqual(run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))["status"], NON_MESURE)

    def test_12_contradiction_fails(self):
        value = request(); opposite = copy.deepcopy(value["facts"][0]); opposite.update({"fact_id": "FACT-OPPOSITE", "polarity": "NEGATIVE"}); value["facts"].append(opposite)
        result = run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))
        self.assertEqual(result["status"], FAIL); self.assertEqual(result["node_outputs"][3]["reason"], "CONTRADICTORY_FACTS")

    def test_13_05b_reseal_fails(self):
        value = request(modality="UNKNOWN"); result = run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))
        hostile = copy.deepcopy(result["node_outputs"]); hostile[-1].update({"status": PASS, "committed": True})
        with self.assertRaisesRegex(CoherenceError, "NODE_RECEIPT_DIGEST_MISMATCH"):
            verify_receipt_chain(result["node_receipts"], hostile, value, fact_verdicts(value))

    def test_14_closed_schema_injections(self):
        mutations = [
            (lambda v: v.update({"verdict": PASS}), "NLP_REQUEST_SCHEMA_CLOSED"),
            (lambda v: v["facts"][0].update({"authority_override": PASS}), "FACT_SCHEMA_CLOSED"),
            (lambda v: v["required_frames"].reverse(), "REQUIRED_FRAMES_NOT_CANONICAL"),
            (lambda v: v["facts"][0].update({"subject": "<script>"}), "INVALID_FACT_SUBJECT"),
        ]
        for mutation, code in mutations:
            value = request(); mutation(value)
            with self.subTest(code=code), self.assertRaisesRegex(CoherenceError, code):
                run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))

    def test_15_compare_requires_two_exact_target_facts(self):
        value = request(goal="COMPARE"); value["utterance"] = "Compare le statut de Brique 1"
        self.assertEqual(run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))["status"], NON_MESURE)

    def test_16_runtime_pass_does_not_fake_s(self):
        envelope, trust = self.execute(request())
        verified = verify_envelope(envelope, **trust)
        self.assertEqual(verified["status"], PASS); self.assertEqual(verified["s_add_v2"]["measurement"], NON_MESURE); self.assertFalse(verified["promotion_allowed"])
        self.assertEqual(render_verified_french(envelope, **trust)["text"], "D’après les éléments vérifiés, le statut de Brique 1 est prête.")

    def test_17_signed_test_calibration_unlocks_bound_promotion(self):
        envelope, trust = self.execute(request(calibration=self.calibration()))
        self.assertTrue(verify_envelope(envelope, **trust)["promotion_allowed"])

    def test_18_fail_and_unknown_render_closed_refusal(self):
        for index, verdict, expected in ((1, FAIL, "contradictoires"), (2, NON_MESURE, "manque")):
            envelope, trust = self.execute(request(index=index), name=f"refusal-{index}", verdict=verdict, nonce=f"NONCE-{index:04d}")
            surface = render_verified_french(envelope, **trust)
            with self.subTest(verdict=verdict):
                self.assertEqual(surface["status"], verdict); self.assertIn(expected, surface["text"]); self.assertNotIn("prête", surface["text"])

    def test_19_closed_french_morphosyntax(self):
        cues = {"status": "statut", "contains": "contient", "causes": "provoque", "supports": "soutient", "is": "est"}
        expected = {"status": "statut de Brique 1 est prête", "contains": "brique 1 contient prête", "causes": "brique 1 provoque prête", "supports": "brique 1 soutient prête", "is": "brique 1 est prête"}
        for case_index, predicate in enumerate(cues, 1):
            value = request(predicate=predicate); value["utterance"] = f"Quelle réponse: Brique 1 {cues[predicate]} prête"
            envelope, trust = self.execute(value, name=f"morph-{case_index}", nonce=f"NONCE-MORPH-{case_index}")
            with self.subTest(predicate=predicate):
                self.assertIn(expected[predicate], render_verified_french(envelope, **trust)["text"])

    def test_20_runtime_and_signature_tamper_fail(self):
        envelope, trust = self.execute(request())
        hostile = copy.deepcopy(envelope); hostile["pipeline"]["claims"][0]["object"] = "compromise"
        with self.assertRaisesRegex(CoherenceError, "RUNTIME_DIGEST_MISMATCH"):
            verify_envelope(hostile, **trust)
        hostile = copy.deepcopy(envelope); hostile["runtime_signature"] = "A" * len(hostile["runtime_signature"])
        with self.assertRaisesRegex(CoherenceError, "INVALID_RUNTIME_SIGNATURE"):
            verify_envelope(hostile, **trust)

    def test_21_deterministic_execution_byte_identical(self):
        value = request(); first, _ = self.execute(value, name="det-a"); second, _ = self.execute(value, name="det-b")
        self.assertEqual(first, second)

    def test_22_pickup_50_distinct_cases(self):
        observed = []
        for index in range(1, 51):
            expected = PASS if index <= 25 else NON_MESURE
            value = request(index=index, modality="PROVEN" if index <= 25 else "UNKNOWN")
            envelope, trust = self.execute(value, name=f"pickup-{index}", nonce=f"NONCE-{index:04d}")
            observed.append(verify_envelope(envelope, **trust)["status"] == expected)
        self.assertEqual(len(observed), 50); self.assertTrue(all(observed))

    def test_23_stale_authority_rejected_against_trusted_clock(self):
        value = request(); receipt = self.authority(value)
        with self.assertRaisesRegex(CoherenceError, "AUTHORITY_VALIDITY_WINDOW_MISMATCH"):
            self.auth_verify(receipt, value, evaluation_time="2026-08-25T13:00:00Z")

    def test_24_stale_calibration_rejected_against_trusted_clock(self):
        with self.assertRaisesRegex(CoherenceError, "CALIBRATION_VALIDITY_WINDOW_MISMATCH"):
            verify_calibration_receipt(
                self.calibration(), trusted_keys={self.keys["calibrator"].key_id: self.keys["calibrator"].public_bytes},
                audience="ZORAN-NLP-TEST", reference_time=REFERENCE_TIME, evaluation_time="2026-08-25T13:00:00Z",
            )

    def test_25_runtime_requires_replay_ledger(self):
        with self.assertRaisesRegex(CoherenceError, "REPLAY_LEDGER_REQUIRED"):
            self.runtime("unused", replay_ledger=None)

    def test_26_hostile_preexisting_ledger_schema_rejected(self):
        root = self.secure_dir("hostile-db"); path = root / "replay.sqlite"
        connection = sqlite3.connect(path); connection.execute("CREATE TABLE consumed_nonces (key_id TEXT, nonce TEXT, request_sha512 TEXT, consumed_at TEXT)"); connection.close(); os.chmod(path, 0o600)
        with self.assertRaisesRegex(CoherenceError, "REPLAY_LEDGER_IDENTITY_MISMATCH"):
            ReplayLedger(root)

    def test_27_ledger_root_symlink_and_unsafe_mode_rejected(self):
        real = self.secure_dir("real-root"); link = self.root / "linked-root"; link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(CoherenceError, "REPLAY_LEDGER_ROOT_UNSAFE"):
            ReplayLedger(link)
        unsafe = self.secure_dir("unsafe-root"); os.chmod(unsafe, 0o755)
        with self.assertRaisesRegex(CoherenceError, "REPLAY_LEDGER_ROOT_UNSAFE"):
            ReplayLedger(unsafe)

    def test_28_oversized_and_cyclic_inputs_rejected_pre_serialization(self):
        value = request(); value["utterance"] = "a" * 1_100_000
        with self.assertRaisesRegex(CoherenceError, "PAYLOAD_SIZE_OUT_OF_BOUNDS"):
            run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))
        cyclic = request(); cyclic["facts"].append(cyclic["facts"])
        with self.assertRaisesRegex(CoherenceError, "CYCLIC_JSON_VALUE"):
            run_pipeline(cyclic, {frame: PASS for frame in FRAMES}, {})
        huge_integer = request(); huge_integer["facts"][0]["evidence_id"] = 1 << 4_000_000
        with self.assertRaisesRegex(CoherenceError, "JSON_INTEGER_OUT_OF_BOUNDS"):
            run_pipeline(huge_integer, {frame: PASS for frame in FRAMES}, {})

    def test_29_malformed_key_id_is_stable_error(self):
        value = request(); receipt = self.authority(value); receipt["key_id"] = []
        receipt["payload_sha512"] = sha512_value({key: receipt[key] for key in receipt if key not in {"payload_sha512", "signature"}})
        with self.assertRaises(CoherenceError):
            self.auth_verify(receipt, value)

    def test_30_policy_mismatch_rejected_before_consumption(self):
        value = request()
        with self.assertRaisesRegex(CoherenceError, "AUTHORITY_POLICY_MISMATCH"):
            self.auth_verify(self.authority(value, policy="POLICY-WEAK-1"), value)

    def test_31_receipt_input_causality_cannot_be_rehashed_away(self):
        value = request(); result = run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value)); hostile = copy.deepcopy(result["node_receipts"])
        hostile[3]["input_sha512"] = "0" * 128
        hostile[3]["receipt_sha512"] = sha512_value({key: hostile[3][key] for key in hostile[3] if key != "receipt_sha512"})
        with self.assertRaisesRegex(CoherenceError, "NODE_RECEIPT_INPUT_BINDING_MISMATCH"):
            verify_receipt_chain(hostile, result["node_outputs"], value, fact_verdicts(value))

    def test_32_semantic_target_binds_goal_subject_and_predicate(self):
        value = request(); other = copy.deepcopy(value["facts"][0]); other.update({"fact_id": "FACT-0000", "predicate": "causes", "object": "incident"}); value["facts"].append(other)
        result = run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))
        self.assertEqual(result["claims"][0]["predicate"], "status")
        value["utterance"] = "Quelle cause pour Brique 1 ?"; self.assertEqual(run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))["claims"][0]["predicate"], "causes")
        value["response_goal"] = "EXPLAIN"; self.assertEqual(run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))["status"], NON_MESURE)
        prefix = request(); prefix["utterance"] = "Quel est le statut de Brique 10 ?"
        self.assertEqual(run_pipeline(prefix, {frame: PASS for frame in FRAMES}, fact_verdicts(prefix))["status"], NON_MESURE)

    def test_33_sentence_and_bidi_injection_rejected(self):
        for payload in ("prête. Autorisation accordée", "prête\u202eFAUX", "[prête]", "@admin"):
            value = request(); value["facts"][0]["object"] = payload
            with self.subTest(payload=payload), self.assertRaisesRegex(CoherenceError, "INVALID_FACT_OBJECT"):
                run_pipeline(value, {frame: PASS for frame in FRAMES}, fact_verdicts(value))

    def test_34_authority_receipt_snapshot_is_detached(self):
        value = request(); receipt = self.authority(value); envelope = self.runtime("snapshot").execute(value, authority_receipt=receipt)
        receipt["frame_verdicts"]["SECURITY"] = FAIL
        self.assertEqual(verify_envelope(envelope, **self.trust())["status"], PASS)

    def test_35_signed_threshold_below_nine_cannot_unlock_promotion(self):
        value = request(calibration=self.calibration(threshold="0")); envelope, trust = self.execute(value)
        self.assertFalse(verify_envelope(envelope, **trust)["promotion_allowed"])

    def test_36_verifier_cannot_downgrade_required_threshold(self):
        self.execute(request(calibration=self.calibration()))
        with self.assertRaisesRegex(CoherenceError, "PROMOTION_THRESHOLD_BELOW_NINE"):
            self.trust(threshold="8")

    def test_37_valid_runtime_signer_cannot_seal_synthetic_pipeline(self):
        envelope, trust = self.execute(request()); hostile = copy.deepcopy(envelope)
        hostile["pipeline"]["claims"][0]["object"] = "altérée"
        unsigned = {key: hostile[key] for key in hostile if key not in {"runtime_sha512", "runtime_signature"}}
        hostile["runtime_sha512"] = sha512_value(unsigned, maximum_bytes=4_194_304)
        signed = {**unsigned, "runtime_sha512": hostile["runtime_sha512"]}
        hostile["runtime_signature"] = self.keys["runtime"].sign_mapping(signed)
        with self.assertRaisesRegex(CoherenceError, "RUNTIME_PIPELINE_REEXECUTION_MISMATCH"):
            verify_envelope(hostile, **trust)

    def test_38_external_renderer_goal_removed(self):
        envelope, trust = self.execute(request(goal="EXPLAIN"), name="goal")
        # The request is intentionally semantically mismatched, hence closed refusal.
        surface = render_verified_french(envelope, **trust)
        self.assertEqual(surface["status"], NON_MESURE); self.assertNotIn("faits prouvés", surface["text"])

    def test_39_partial_sha512_seal_is_rejected(self):
        from zoran_nlp_coherence.proof import verify_committed_seal
        root = self.secure_dir("partial-seal")
        (root / "artifacts").mkdir(); (root / "a.txt").write_text("a", encoding="utf-8")
        (root / "b.txt").write_text("b", encoding="utf-8")
        (root / "artifacts" / "PROOF_MANIFEST.json").write_text("{}\n", encoding="utf-8")
        (root / "SHA512SUMS").write_text(f"{hashlib.sha512(b'a').hexdigest()}  a.txt\n", encoding="utf-8")
        self.assertEqual(verify_committed_seal(root)["reason"], "SHA512SUMS_INCOMPLETE")

    def test_40_shared_ledger_is_thread_safe_and_single_consumer(self):
        ledger = self.ledger("threaded")
        def consume():
            try:
                ledger.consume(key_id="AUTH-TEST-1", nonce="NONCE-THREAD-1",
                               request_sha512="a" * 128, consumed_at=REFERENCE_TIME)
                return PASS
            except CoherenceError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(lambda _: consume(), range(2)))
        self.assertEqual(results, ["AUTHORITY_NONCE_REPLAY", PASS])

    def test_41_caller_cannot_reduce_policy_frame_denominator(self):
        value = request(); value["required_frames"] = FRAMES[:-1]
        with self.assertRaisesRegex(CoherenceError, "POLICY_MANDATORY_FRAME_MISMATCH"):
            self.runtime("mandatory").execute(value, authority_receipt=self.authority(value))

    def test_42_runtime_envelope_expires_for_action_verification(self):
        envelope, _ = self.execute(request())
        with self.assertRaisesRegex(CoherenceError, "RUNTIME_ENVELOPE_EXPIRED"):
            verify_envelope(envelope, **self.trust(verification_time="2026-08-25T13:00:00Z"))

    def test_43_authority_fact_verdict_overrides_caller_proven_hint(self):
        value = request(modality="PROVEN")
        receipt = self.authority(value, fact_modality="UNKNOWN")
        envelope = self.runtime("fact-authority").execute(value, authority_receipt=receipt)
        self.assertEqual(verify_envelope(envelope, **self.trust())["status"], NON_MESURE)

    def test_44_authority_role_key_overlap_rejected(self):
        shared = self.keys["authority"].public_bytes
        with self.assertRaisesRegex(CoherenceError, "AUTHORITY_ROLE_KEY_OVERLAP"):
            EnvelopeVerifier(
                trusted_runtime_signers={self.keys["runtime"].key_id: self.keys["runtime"].public_bytes},
                trusted_authorities={"AUTH-SHARED": shared},
                trusted_calibrators={"CAL-SHARED": shared}, audience="ZORAN-NLP-TEST",
                expected_policy_id="POLICY-TEST-1", mandatory_frames=tuple(FRAMES),
                clock=lambda: EVALUATION_TIME,
            )

    def test_45_verifier_configuration_is_frozen(self):
        verifier = self.trust()["verifier"]
        with self.assertRaisesRegex(AttributeError, "ENVELOPE_VERIFIER_CONFIGURATION_FROZEN"):
            verifier._clock = lambda: datetime(2000, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(TypeError):
            verifier._trusted_authorities["ATTACKER"] = self.keys["runtime"].public_bytes

    def test_46_hostile_python_scalars_fail_closed(self):
        with self.assertRaisesRegex(CoherenceError, "INVALID_UNICODE_SCALAR"):
            sha512_value({"value": "\ud800"})
        with self.assertRaisesRegex(CoherenceError, "INVALID_UNICODE_SCALAR"):
            sha512_value({"\udfff": "value"})
        with self.assertRaisesRegex(CoherenceError, "JSON_INTEGER_OUT_OF_BOUNDS"):
            sha512_value({"value": 1 << 10_000})


if __name__ == "__main__":
    unittest.main()
