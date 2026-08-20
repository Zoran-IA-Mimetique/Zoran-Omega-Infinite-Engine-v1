# S_ADD_V2 — moteur de variantes exhaustif dans `FORM_GRAMMAR_V1`

**Équation canonique actuelle :**

```
S_ADD_V2 = (β × ΔΦ)/(1 + T + σ)
```

Le terme `1` est **obligatoire**. Le dénominateur est **strictement additif**.

**DOI source :** [10.5281/zenodo.17559249](https://doi.org/10.5281/zenodo.17559249)
**Auteur :** Frédéric Tabary — Institut IA Inc. / Coherence Labs
**Licence :** MIT (inchangée)

---

## Ce que ce moteur fait

Il dérive, par clôture symbolique réelle (SymPy), l'ensemble des formes admises
par une grammaire fermée et versionnée — `FORM_GRAMMAR_V1` — à partir du seul
résidu :

```
F = S × D − β × ΔΦ = 0,    D = 1 + T + σ
```

Il n'y a **aucune liste de formes codée en dur**. Les formes naissent de
l'application répétée des règles de réécriture jusqu'à un point fixe, suivie
d'une seconde ronde vide qui atteste la saturation.

## Ce que ce moteur ne prétend pas

Il ne prétend pas énumérer « toutes les formes possibles ». Les reformulations
syntaxiques arbitraires sont infinies : on peut toujours ajouter le même terme
aux deux membres, multiplier par une fonction non nulle, ou renommer les
symboles. La grammaire exclut explicitement ces opérations (`X1`–`X5`).

La seule revendication admise est :

> **Exhaustif dans `FORM_GRAMMAR_V1`.**

La validation physique externe reste **`NON_MESURÉ`** et distincte de la clôture
formelle.

---

## Contradiction historique corrigée

| Source | Ce qu'elle annonce | Ce qu'elle fait réellement |
|---|---|---|
| Notice DOI 17559249 | « toutes les formulations possibles », famille illimitée, 94 formes | — |
| `variant_engine.py` (Zenodo) | — | **20 chaînes codées en dur**, docstring : *« illustrative rather than exhaustive »*, équation `S = (β·ΔC)/λ` |
| `PITON_PLUS.py` | falsification | balayage **numérique aléatoire**, aucune fermeture symbolique |
| **Ce moteur** | exhaustivité **bornée et déclarée** | clôture par point fixe, preuve d'équivalence par forme, empreintes SHA-256 |

---

## Résultat central

Le noyau algébrique — forme canonique, croisée factorisée, croisée développée,
résidu nul, les cinq isolations et les huit proportions — **s'effondre en une
seule classe sémantique**. Ce ne sont pas des lois différentes : c'est une
seule loi écrite de plusieurs manières.

Les chiffres exacts sont produits par l'exécution, jamais fixés à la main. Ils
figurent dans `artifacts/PROOF_MANIFEST.json`.

---

## Utilisation

```bash
python -m pip install -e ".[test]"
python -m pytest -q
python -m s_add_v2_variant_engine.variant_engine_s_add_v2 --output artifacts/
```

Seuil d'admissibilité paramétrable :

```bash
python -m s_add_v2_variant_engine.variant_engine_s_add_v2 --output artifacts/ --theta 1
```

### API minimale

```python
from s_add_v2_variant_engine.variant_engine_s_add_v2 import (
    compute_s_add_v2, is_admissible, build_variants,
)

compute_s_add_v2(beta=0.9, dphi=0.8, tension=0.2, sigma=0.1)  # 0.5538...
is_admissible(0.9, 0.8, 0.2, 0.1, theta=1.0)                  # False
build_variants(theta=1)["counts"]
```

`compute_s_add_v2` refuse `NaN`, `Inf`, les types invalides, et — en mode
`PHYSICAL` — les valeurs `T < 0` ou `σ < 0`. Aucun `epsilon` de régularisation
n'est appliqué : le terme unité rend `D ≥ 1` sur tout le domaine physique.

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `FORM_GRAMMAR_V1.json` | grammaire fermée, versionnée, avec ses exclusions |
| `variant_engine_s_add_v2.py` | moteur symbolique + évaluateur numérique strict |
| `SCHEMA_S_ADD_V2_VARIANTS.json` | schéma JSON des artefacts |
| `tests/test_variant_engine.py` | falsificateurs et tests de non-régression |
| `artifacts/S_ADD_V2_VARIANTS.json` | formes, gardes, preuves, empreintes |
| `artifacts/PROOF_MANIFEST.json` | manifeste de preuve, compteurs, `DETTE_COH` |

---

## Déterminisme

Même entrée et même version de grammaire ⇒ mêmes formes, même ordre, mêmes
empreintes, octet pour octet. La partie canonique du manifeste est hachée
**sans** les métadonnées d'exécution (commit, horodatage, plateforme), de sorte
qu'un `SOURCE_DATE_EPOCH` différent ne modifie jamais `canonical_sha256`.

**Portée exacte de cette garantie.** L'identité octet à octet vaut **à version
de SymPy fixée** (voir `requirements-lock.txt`, référence `sympy==1.14.0`) :
les empreintes sémantiques reposent sur `srepr`, dont la sortie peut évoluer
entre versions de SymPy. Le déterminisme *interne* — deux constructions dans un
même environnement — est garanti sur toute version supportée, et c'est ce que
vérifie la matrice CI 3.9 → 3.12. Le CI teste les deux propriétés séparément
plutôt que de les confondre.

## Dette de cohérence déclarée

Voir `DETTE_COH` dans `artifacts/PROOF_MANIFEST.json`. En résumé : l'exhaustivité
est relative à `FORM_GRAMMAR_V1` et à elle seule ; le seuil `θ = 1` est logique
et non calibré ; les proxies de `β`, `ΔΦ`, `T`, `σ` ne sont pas fixés ici ; la
validation physique externe est `NON_MESURÉ`.
