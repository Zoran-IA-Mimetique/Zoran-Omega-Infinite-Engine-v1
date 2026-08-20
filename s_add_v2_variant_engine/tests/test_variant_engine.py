# -*- coding: utf-8 -*-
"""Tests du moteur S_ADD_V2. Aucun accès réseau.

Canon testé : S_ADD_V2 = (β × ΔΦ)/(1 + T + σ)
DOI         : 10.5281/zenodo.17559249
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest
import sympy as sp

from s_add_v2_variant_engine.variant_engine_s_add_v2 import (
    BETA, CANONICAL_ASCII, CANONICAL_UNICODE, CANONICAL_RHS, CORE_RESIDUAL, D,
    DPHI, GRAMMAR_VERSION, HISTORIQUE_NON_CANONIQUE, REJECTED_FORMS, S,
    SIGMA, SOURCE_DOI, T, SAddV2Error, build_manifest, build_variants,
    canonical_json, classify_rhs, compute_s_add_v2,
    denominator_is_strictly_additive, grammar_sha256, is_admissible,
    sha256_of,
)

PKG = Path(__file__).resolve().parent.parent
REPO = PKG.parent
ARTIFACTS = PKG / "artifacts"

# construit une seule fois : coûteux en SymPy
VARIANTS = build_variants(1)


# --------------------------------------------------------------------------
# 1. Canon
# --------------------------------------------------------------------------

def test_canonical_equation_is_strictly_additive_with_unit():
    assert sp.simplify(CANONICAL_RHS - BETA * DPHI / (1 + T + SIGMA)) == 0
    assert denominator_is_strictly_additive(CANONICAL_RHS)
    _num, den = sp.fraction(sp.cancel(sp.together(CANONICAL_RHS)))
    assert sp.expand(den) == sp.expand(1 + T + SIGMA)
    # le terme unité est présent : D vaut 1 quand T = σ = 0
    assert den.subs({T: 0, SIGMA: 0}) == 1


def test_core_residual_matches_canonical():
    assert sp.simplify(CORE_RESIDUAL.subs(S, CANONICAL_RHS)) == 0


def test_canonical_strings_agree():
    assert "1 + T + σ" in CANONICAL_UNICODE
    assert "1 + T + sigma" in CANONICAL_ASCII


# --------------------------------------------------------------------------
# 2. Équivalence symbolique — exhaustif sur TOUTES les formes
# --------------------------------------------------------------------------

def test_every_form_has_verified_equivalence_proof():
    assert VARIANTS["variants"], "aucune forme générée"
    for v in VARIANTS["variants"]:
        assert v["equivalence_proof"]["verified"] is True, v["variant_id"]
        assert v["status"] == "PASS", v["variant_id"]


def test_every_equation_form_reduces_to_zero_symbolically():
    E_Z = sp.Symbol("E_Z", real=True)
    for v in VARIANTS["variants"]:
        if v["relation"] != "Eq":
            continue
        payload = json.loads(v["sympy_serialization"])
        lhs = sp.sympify(payload["lhs"])
        rhs = sp.sympify(payload["rhs"])
        residual = (lhs - rhs).subs(E_Z, -sp.log(S)).subs(S, CANONICAL_RHS)
        if v["category"] in ("LOGARITHMIC", "ENERGY"):
            pos = {sym: sp.Symbol(sym.name, positive=True)
                   for sym in (BETA, DPHI, T, SIGMA)}
            residual = sp.expand_log(sp.simplify(residual.subs(pos)), force=True)
        assert sp.simplify(residual) == 0, v["variant_id"]


# --------------------------------------------------------------------------
# 3. Gardes
# --------------------------------------------------------------------------

GUARD_FOR_SOLVED = {
    "S": "1 + T + sigma != 0",
    "beta": "DeltaPhi != 0",
    "DeltaPhi": "beta != 0",
    "T": "S != 0",
    "sigma": "S != 0",
}


def test_isolation_forms_carry_their_guard():
    seen = set()
    for v in VARIANTS["variants"]:
        if v["category"] != "ISOLATION":
            continue
        expected = GUARD_FOR_SOLVED[v["solved_for"]]
        assert expected in v["domain_guards"], v["variant_id"]
        seen.add(v["solved_for"])
    assert seen == set(GUARD_FOR_SOLVED), seen


def test_no_division_without_guard():
    """Toute forme comportant un dénominateur symbolique porte au moins une garde."""
    for v in VARIANTS["variants"]:
        payload = json.loads(v["sympy_serialization"])
        for side in ("lhs", "rhs"):
            expr = sp.sympify(payload[side])
            _num, den = sp.fraction(sp.cancel(sp.together(expr)))
            if den.free_symbols:
                assert v["domain_guards"], f"{v['variant_id']} sans garde"


def test_logarithmic_forms_require_positivity():
    for v in VARIANTS["variants"]:
        if v["category"] != "LOGARITHMIC":
            continue
        for guard in ("S > 0", "beta > 0", "DeltaPhi > 0"):
            assert guard in v["domain_guards"], v["variant_id"]


# --------------------------------------------------------------------------
# 4. Identifiants et empreintes
# --------------------------------------------------------------------------

def test_variant_ids_are_unique():
    ids = [v["variant_id"] for v in VARIANTS["variants"]]
    assert len(ids) == len(set(ids))


def test_every_variant_carries_grammar_and_doi():
    for v in VARIANTS["variants"]:
        assert v["source_doi"] == SOURCE_DOI
        assert v["grammar_version"] == GRAMMAR_VERSION
        assert len(v["semantic_sha256"]) == 64


def test_core_algebraic_forms_share_one_semantic_class():
    """Résultat central : le noyau algébrique est UNE seule loi."""
    core = {v["semantic_sha256"] for v in VARIANTS["variants"]
            if v["category"] in ("RATIONAL_CANONICAL", "CROSS_FACTORED",
                                 "CROSS_EXPANDED", "ZERO_RESIDUAL",
                                 "ISOLATION", "PROPORTION")}
    assert len(core) == 1, f"attendu 1 classe, obtenu {len(core)}"


def test_renderings_are_four_per_oriented_form():
    c = VARIANTS["counts"]
    assert c["renderings"] == 4 * c["oriented_forms"]
    for v in VARIANTS["variants"]:
        for field in ("expression_ascii", "expression_unicode",
                      "expression_latex", "sympy_serialization"):
            assert v[field], f"{v['variant_id']} rendu {field} vide"


# --------------------------------------------------------------------------
# 5. Déterminisme bit à bit
# --------------------------------------------------------------------------

def test_two_builds_are_bitwise_identical():
    a = canonical_json(build_variants(1))
    b = canonical_json(build_variants(1))
    assert a == b
    assert sha256_of(build_variants(1)) == sha256_of(build_variants(1))


def test_manifest_canonical_hash_is_timestamp_independent():
    g = grammar_sha256(PKG)
    m1 = build_manifest(VARIANTS, g, "COMMIT_A")
    m2 = build_manifest(VARIANTS, g, "COMMIT_B")
    # le commit vit dans les métadonnées d'exécution, hors partie hachée
    assert m1["canonical_sha256"] == m2["canonical_sha256"]
    assert m1["runtime_metadata_not_hashed"]["git_commit"] != \
        m2["runtime_metadata_not_hashed"]["git_commit"]


# --------------------------------------------------------------------------
# 6. Saturation
# --------------------------------------------------------------------------

def test_saturation_ends_with_two_empty_rounds():
    rounds = VARIANTS["saturation_rounds"]
    assert len(rounds) >= 3
    assert rounds[-1]["new_forms"] == 0
    assert rounds[-2]["new_forms"] == 0
    assert rounds[-1].get("attestation") == "SECOND_EMPTY_ROUND"


def test_saturation_had_productive_rounds():
    productive = [r for r in VARIANTS["saturation_rounds"] if r["new_forms"] > 0]
    assert len(productive) >= 2, "la clôture doit être réellement itérative"


# --------------------------------------------------------------------------
# 7. Jeux numériques déterministes (>= 50)
# --------------------------------------------------------------------------

BETAS = (0.25, 0.5, 1.0, 2.0)
DPHIS = (0.5, 1.0, 3.0)
TS = (0.0, 0.5, 2.0)
SIGMAS = (0.0, 0.25, 1.5)
GRID = tuple(itertools.product(BETAS, DPHIS, TS, SIGMAS))


def test_grid_has_at_least_fifty_points():
    assert len(GRID) >= 50, len(GRID)


def test_numeric_consistency_of_canonical_formula():
    for b, dp, t, sg in GRID:
        expected = (b * dp) / (1.0 + t + sg)
        assert compute_s_add_v2(b, dp, t, sg) == pytest.approx(expected, rel=1e-12)


def test_all_equation_forms_hold_numerically_on_grid():
    E_Z = sp.Symbol("E_Z", real=True)
    checked = 0
    for v in VARIANTS["variants"]:
        if v["relation"] != "Eq":
            continue
        payload = json.loads(v["sympy_serialization"])
        lhs, rhs = sp.sympify(payload["lhs"]), sp.sympify(payload["rhs"])
        evaluated = 0
        for b, dp, t, sg in GRID:
            s_val = (b * dp) / (1.0 + t + sg)
            if v["category"] in ("LOGARITHMIC", "ENERGY"):
                if min(b, dp, s_val) <= 0:
                    continue
            if v["solved_for"] in ("T", "sigma") and s_val == 0:
                continue
            if v["solved_for"] == "beta" and dp == 0:
                continue
            if v["solved_for"] == "DeltaPhi" and b == 0:
                continue
            subs = {S: s_val, BETA: b, DPHI: dp, T: t, SIGMA: sg,
                    E_Z: -math.log(s_val) if s_val > 0 else 0}
            left = complex(sp.N(lhs.subs(subs)))
            right = complex(sp.N(rhs.subs(subs)))
            assert abs(left - right) < 1e-9, (v["variant_id"], b, dp, t, sg)
            evaluated += 1
        assert evaluated >= 50, (v["variant_id"], evaluated)
        checked += 1
    assert checked >= 30


def test_admissibility_forms_agree_with_direct_threshold():
    for b, dp, t, sg in GRID:
        s_val = compute_s_add_v2(b, dp, t, sg)
        assert is_admissible(b, dp, t, sg, theta=1.0) == (s_val >= 1.0)
        assert is_admissible(b, dp, t, sg, theta=1.0, strict=True) == (s_val > 1.0)
        # forme dégagée du dénominateur : équivalente car D > 0
        assert (b * dp >= 1.0 * (1.0 + t + sg)) == (s_val >= 1.0)


# --------------------------------------------------------------------------
# 8. Cas nuls, selon les gardes
# --------------------------------------------------------------------------

def test_beta_zero_gives_zero_and_is_inadmissible():
    assert compute_s_add_v2(0.0, 5.0, 0.3, 0.2) == 0.0
    assert not is_admissible(0.0, 5.0, 0.3, 0.2)


def test_dphi_zero_gives_zero():
    assert compute_s_add_v2(5.0, 0.0, 0.3, 0.2) == 0.0


def test_s_zero_blocks_isolation_of_T_and_sigma():
    """S = 0 viole la garde S != 0 des isolations de T et σ."""
    b, dp, t, sg = 0.0, 1.0, 0.5, 0.5
    assert compute_s_add_v2(b, dp, t, sg) == 0.0
    for v in VARIANTS["variants"]:
        if v["category"] == "ISOLATION" and v["solved_for"] in ("T", "sigma"):
            assert "S != 0" in v["domain_guards"]


# --------------------------------------------------------------------------
# 9. Rejets d'entrée
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_reject_non_finite(bad):
    with pytest.raises(SAddV2Error):
        compute_s_add_v2(bad, 1.0, 0.0, 0.0)
    with pytest.raises(SAddV2Error):
        compute_s_add_v2(1.0, bad, 0.0, 0.0)


@pytest.mark.parametrize("bad", ["1.0", None, [1.0], {"v": 1}, True, complex(1, 1)])
def test_reject_invalid_types(bad):
    with pytest.raises(SAddV2Error):
        compute_s_add_v2(bad, 1.0, 0.0, 0.0)


def test_reject_zero_denominator_in_real_mode():
    with pytest.raises(SAddV2Error):
        compute_s_add_v2(1.0, 1.0, -1.0, 0.0, mode="REAL")


def test_physical_mode_rejects_negative_domain():
    with pytest.raises(SAddV2Error):
        compute_s_add_v2(1.0, 1.0, -0.5, 0.0)
    with pytest.raises(SAddV2Error):
        compute_s_add_v2(1.0, 1.0, 0.0, -0.5)


def test_physical_mode_denominator_always_at_least_one():
    for b, dp, t, sg in GRID:
        assert 1.0 + t + sg >= 1.0
        compute_s_add_v2(b, dp, t, sg)  # ne lève jamais


def test_unknown_mode_rejected():
    with pytest.raises(SAddV2Error):
        compute_s_add_v2(1.0, 1.0, 0.0, 0.0, mode="MAGIC")


# --------------------------------------------------------------------------
# 10. Rejet des formes historiques non canoniques
# --------------------------------------------------------------------------

def test_multiplicative_denominator_is_rejected():
    assert classify_rhs(BETA * DPHI / (T * SIGMA)) == HISTORIQUE_NON_CANONIQUE
    assert not denominator_is_strictly_additive(BETA * DPHI / (T * SIGMA))


def test_additive_without_unit_is_rejected():
    assert classify_rhs(BETA * DPHI / (T + SIGMA)) == HISTORIQUE_NON_CANONIQUE


@pytest.mark.parametrize("factor", [10, 100])
def test_scaled_variants_are_rejected(factor):
    assert classify_rhs(factor * BETA * DPHI / D) == HISTORIQUE_NON_CANONIQUE


def test_lambda_single_variable_denominator_is_rejected():
    lam = sp.Symbol("lambda", real=True)
    assert classify_rhs(BETA * DPHI / lam) == HISTORIQUE_NON_CANONIQUE


def test_canonical_form_is_accepted():
    assert classify_rhs(CANONICAL_RHS) == "CANONIQUE"
    assert classify_rhs(BETA * DPHI / (1 + T + SIGMA)) == "CANONIQUE"
    # réécriture équivalente : toujours canonique
    assert classify_rhs(sp.expand(BETA * DPHI) / sp.expand(1 + T + SIGMA)) == "CANONIQUE"


def test_all_declared_rejections_are_reported_in_artifact():
    reported = {r["id"] for r in VARIANTS["rejected_historical_forms"]}
    assert reported == {rid for rid, _e, _r in REJECTED_FORMS}
    for r in VARIANTS["rejected_historical_forms"]:
        assert r["classification_result"] == HISTORIQUE_NON_CANONIQUE


def test_no_generated_form_uses_a_multiplicative_denominator():
    for v in VARIANTS["variants"]:
        payload = json.loads(v["sympy_serialization"])
        for side in ("lhs", "rhs"):
            expr = sp.sympify(payload[side])
            _num, den = sp.fraction(sp.cancel(sp.together(expr)))
            if den.free_symbols and sp.expand(den) != sp.expand(D):
                # seules les proportions introduisent d'autres dénominateurs
                assert v["category"] in ("PROPORTION", "ISOLATION"), v["variant_id"]


# --------------------------------------------------------------------------
# 11. Schéma JSON
# --------------------------------------------------------------------------

REQUIRED_VARIANT_FIELDS = (
    "variant_id", "grammar_version", "category", "expression_unicode",
    "expression_ascii", "expression_latex", "sympy_serialization",
    "domain_guards", "equivalence_proof", "semantic_sha256", "source_doi",
    "status",
)


def test_artifact_matches_json_schema():
    schema = json.loads((PKG / "SCHEMA_S_ADD_V2_VARIANTS.json").read_text("utf-8"))
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance=VARIANTS, schema=schema)


def test_every_variant_has_all_required_fields():
    for v in VARIANTS["variants"]:
        for field in REQUIRED_VARIANT_FIELDS:
            assert field in v, f"{v.get('variant_id')} manque {field}"
        assert v["status"] in ("PASS", "FAIL", "NON_MESURÉ")


# --------------------------------------------------------------------------
# 12. DOI et vocabulaire
# --------------------------------------------------------------------------

DOI_FILES = (
    PKG / "variant_engine_s_add_v2.py",
    PKG / "README.md",
    PKG / "FORM_GRAMMAR_V1.json",
    REPO / "CITATION.cff",
    REPO / "zenodo.json",
    REPO / "README.md",
)


@pytest.mark.parametrize("path", DOI_FILES, ids=lambda p: p.name)
def test_doi_present_in_file(path):
    assert SOURCE_DOI in path.read_text("utf-8"), f"DOI absent de {path}"


def test_doi_present_in_generated_payloads():
    assert VARIANTS["source_doi"] == SOURCE_DOI
    manifest = build_manifest(VARIANTS, grammar_sha256(PKG), "X")
    assert manifest["canonical"]["source_doi"] == SOURCE_DOI


FORBIDDEN_WORDING = ("validé scientifiquement", "famille illimitée",
                     "toutes les formes possibles")


def test_forbidden_wording_absent_from_generated_payloads():
    """Le moteur ne doit jamais ÉMETTRE une de ces formulations."""
    blob = canonical_json(VARIANTS)
    manifest_blob = canonical_json(
        build_manifest(VARIANTS, grammar_sha256(PKG), "X"))
    for phrase in FORBIDDEN_WORDING:
        assert phrase not in blob, f"artefact contient « {phrase} »"
        assert phrase not in manifest_blob, f"manifeste contient « {phrase} »"


def test_forbidden_wording_only_ever_quoted_never_asserted():
    """La documentation peut CITER ces formulations pour les rejeter.

    Elle ne peut pas les employer à son compte. On vérifie donc que chaque
    occurrence vit dans une ligne de citation : ligne de tableau markdown, ou
    ligne portant des guillemets français.
    """
    for path in (PKG / "README.md", PKG / "variant_engine_s_add_v2.py"):
        for lineno, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            for phrase in FORBIDDEN_WORDING:
                if phrase not in line:
                    continue
                quoted = line.lstrip().startswith("|") or "«" in line
                assert quoted, f"{path.name}:{lineno} affirme « {phrase} »"


def test_exhaustiveness_claim_is_bounded():
    assert VARIANTS["exhaustiveness_claim"] == "Exhaustif dans FORM_GRAMMAR_V1."


def test_manifest_declares_external_validation_unmeasured():
    manifest = build_manifest(VARIANTS, grammar_sha256(PKG), "X")
    assert manifest["canonical"]["external_physical_validation"] == "NON_MESURÉ"
    assert manifest["canonical"]["DETTE_COH"], "dette de cohérence non déclarée"
