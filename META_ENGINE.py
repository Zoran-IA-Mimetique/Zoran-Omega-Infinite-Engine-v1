import numpy as np
import pandas as pd
import warnings

class ZoranMetaEngine:
    """
    META-ENGINE: The Official Implementation of the Zoran Ω∞ Coherence Law.

    Theoretical Basis:
    S = (beta * d_phi) / (T * sigma)

    Where:
    - beta: Intention / Directional Alignment
    - d_phi: Organizational Flux / Structural Density
    - T: Internal Tension / Constraints
    - sigma: Noise / Entropy
    """

    def __init__(self, sigma_min=1e-6, T_min=1e-6):
        # Constants to prevent singularities in noise-free or tension-free theoretical systems
        self.sigma_min = sigma_min
        self.T_min = T_min
        self.history = []

    def compute_s(self, beta, d_phi, T, sigma, record=True):
        """
        Calculates instantaneous Coherence S.
        Returns a dictionary with raw variables, S score, and stability state.
        """
        # Apply physical bounds
        eff_sigma = max(float(sigma), self.sigma_min)
        eff_T = max(float(T), self.T_min)

        # The Universal Equation
        try:
            S = (beta * d_phi) / (eff_T * eff_sigma)
        except ZeroDivisionError:
            S = 0.0

        # Determine Regime
        if S > 1.0:
            state = "REGENERATIVE"
        elif 0.95 <= S <= 1.05:
            state = "CRITICAL_UNSTABLE"
        else:
            state = "DEGRADING"

        result = {
            "beta": beta,
            "d_phi": d_phi,
            "T": eff_T,
            "sigma": eff_sigma,
            "S": S,
            "state": state
        }

        if record:
            self.history.append(result)

        return result

    def map_llm_signal(self, row):
        """
        Operational Mapping for Large Language Models (Transformer Architecture).
        Based on Paper Table 1.

        Expected Input (dict/row): 
        - perplexity (float)
        - delta_h_norm (float): Magnitude of activation update
        - attention_KL (float): Divergence between heads
        - entropy (float): Token-level entropy
        """
        beta = 1.0 / (1.0 + np.log1p(row.get('perplexity', 1.0)))
        d_phi = row.get('delta_h_norm', 0.5)
        T = row.get('attention_KL', 0.5)
        sigma = row.get('entropy', 0.5)
        return beta, d_phi, T, sigma

    def map_ecg_signal(self, rr_ms, baseline_target=800):
        """
        Operational Mapping for Physiological Systems (ECG).
        """
        deviation = abs(rr_ms - baseline_target)
        beta = 1.0 / (1.0 + (deviation / 100.0))
        d_phi = 1000.0 / max(rr_ms, 1.0)
        T = 0.5
        sigma = 0.05
        return beta, d_phi, T, sigma

    def get_history_df(self):
        return pd.DataFrame(self.history)
