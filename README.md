# Zoran Ω∞ — Universal Coherence Engine Pack (v1.0.0)

**Official implementation of the Universal Coherence Law S = (β·ΔΦ) / (T·σ)**  
Author: **Frédéric Tabary — Institut IA Inc. / Coherence Labs**  
DOI: https://doi.org/10.5281/zenodo.17751407  

---

## 🔬 Overview

The **Zoran Ω∞ Engine Pack** provides the full operational implementation of the  
**Universal Law of Coherence**, a quantitative, falsifiable measure of system stability:

\[
S = \frac{\beta \cdot \Delta \Phi}{T \cdot \sigma}
\]

### Interpretation
- **S > 1** → *Regenerative system*  
- **0.95 ≤ S ≤ 1.05** → *Critical system*  
- **S < 1** → *Degrading system*

### Universal Mapping  
| Variable | Meaning | Example (LLM) | Example (Physiology) |
|---------|---------|----------------|-----------------------|
| **β**   | Intention / Alignment | Perplexity inverse | RR interval deviation |
| **ΔΦ**  | Organizational flux | Activation flow | Metabolic flux |
| **T**   | Internal tension | Attention-head KL | Sympathetic tension |
| **σ**   | Noise / Entropy | Token entropy | HRV jitter |

The engine applies to:
- LLM reasoning traces  
- ECG / physiological signals  
- Cognitive systems  
- Multi-agent systems  
- Synthetic datasets  

---

## 📁 Repository Structure
---

## ⚙️ Installation

Requirements:
- Python 3.8+
- numpy ≥ 1.21  
- pandas ≥ 1.3  
- matplotlib ≥ 3.4  
- jupyter ≥ 1.0  

Install dependencies:

```bash
pip install -r requirements.txt
from META_ENGINE import ZoranMetaEngine

engine = ZoranMetaEngine()
result = engine.compute_s(beta=0.9, d_phi=0.8, T=0.2, sigma=0.1)

print(result["S"], result["state"])

import pandas as pd
from META_ENGINE import ZoranMetaEngine

engine = ZoranMetaEngine()
df = pd.read_csv("LLM_activation_dataset.csv")

df["S"] = df.apply(
    lambda row: engine.compute_s(*engine.map_llm_signal(row))["S"],
    axis=1
)

print(df)

from PITON_PLUS import PitonFalsifier

piton = PitonFalsifier(n_simulations=1000000)
df = piton.run_fractal_sweep()
report = piton.extract_micro_laws(df)

print(report)


📊 Reproducibility & FAIR Compliance

This repository follows FAIR standards:

Findable: DOI + citation metadata

Accessible: MIT license, public datasets

Interoperable: CSV + Python

Reusable: Complete engine + notebook + metadata


Included:

CITATION.cff for scholarly citation

zenodo.json for Zenodo DOI integration

Complete code to reproduce all figures



---

📚 Scientific Reference

Tabary, F. (2025).
Universal Coherence: A Unified and Falsifiable Law of System Stability Across Scales.
Submitted to Nature Machine Intelligence.
DOI: https://doi.org/10.5281/zenodo.17750133

Software citation:
Tabary, F. (2025). Zoran Ω∞ Engine Pack (v1.0.0).
DOI: https://doi.org/10.5281/zenodo.17751407


---

📄 License

Released under the MIT License.
© 2025 Frédéric Tabary — Institut IA Inc. / Coherence Labs


---

✉️ Contact

Frédéric Tabary
Institut IA Inc. — Coherence Labs
📧 tabary01@gmail.com


---

🤝 Contributions

Contributions are welcome under MIT guidelines.

To contribute:

Submit an issue or pull request

Describe the modification

Include tests if relevant

Provide rationale and expected impact



---

🕘 Changelog

v1.0.0 — First Public Release

META-ENGINE

PITON+

LLM & ECG datasets

Full reproducibility notebook

Zenodo metadata

MIT license

Complete documentation



---

⚠️ Disclaimer

This software is provided “as is”, without warranty of any kind.
It is intended for research and educational purposes only.

---
