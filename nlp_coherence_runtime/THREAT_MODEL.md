# Threat model — NLP coherence runtime v1

| Boundary | Attacker capability | Required control | Implemented evidence |
|---|---|---|---|
| Caller → request | open fields, pre-serialization memory exhaustion, cyclic values, oversized integers or hostile Unicode | closed schemas, incremental byte budget, integer-bit ceiling, surrogate veto, cycle veto, NFKC and noun-phrase allowlist | tests 14/28/33/46 |
| Caller → frames | omit a failing frame or inject `PASS` | policy-derived mandatory denominator plus exact signed coverage | tests 01–04/41 |
| Caller → facts | self-label an assertion `PROVEN` | signed fact/evidence verdict bound to both SHA-512 values | test 43; `authority.py` |
| Receipt → runtime | replay, reset the DB or swap policy/time | mandatory confined ledger, schema/inode check, policy and trusted-clock binding | tests 05/23/25–27/30 |
| 00→05 nodes | replace a real output with synthetic `PASS` | causal input/output SHA-512 chain plus full deterministic re-execution | tests 09/13/20/31/37 |
| 05 → 05B | self-approve after selection | inherited K3 conjunction | tests 10/13 |
| Runtime → NLG | alter, replay, age, or change claims/goal after decision | private snapshot, current-time expiry, signed goal, strict lexemes and re-execution | tests 16/20/33/34/37/38/42 |
| Calibration → promotion | fabricate S, stale receipt or threshold downgrade | separate trust store, trusted clock, signed bounds and hard floor `>9` | tests 06–08/17/24/35/36 |
| Semantic target | steer the answer via fact ID, wrong goal or wrong predicate | exact goal/subject/predicate target and ambiguity veto | tests 15/32 |
| CI supply chain | mutable Action/package input | Action commit SHAs, hash-locked wheels, seal check before execution | workflow; `requirements-lock.txt` |

Residual risks remain `NON_MESURÉ`: production key custody, OS compromise,
side-channel resistance, multilingual pragmatics, human naturalness, external
corpus representativeness and scientific calibration of β, ΔΦ, T and σ.
