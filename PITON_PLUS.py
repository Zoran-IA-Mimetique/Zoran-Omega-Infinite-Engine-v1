import numpy as np
import pandas as pd
from META_ENGINE import ZoranMetaEngine
import time

class PitonFalsifier:
    """
    PITON+: Fractal Falsification & Micro-Law Detection Engine.
    """

    def __init__(self, n_simulations=100000):
        self.n_simulations = n_simulations
        self.engine = ZoranMetaEngine()

    def run_fractal_sweep(self):
        print(f"[PITON+] Initiating Fractal Sweep on {self.n_simulations} vectors...")
        start_time = time.time()
        betas = np.random.uniform(0.01, 1.0, self.n_simulations)
        d_phis = np.random.lognormal(mean=0.0, sigma=0.5, size=self.n_simulations)
        Ts = np.random.normal(loc=0.5, scale=0.15, size=self.n_simulations)
        Ts = np.clip(Ts, 0.01, 1.0)
        sigmas = np.random.exponential(scale=0.2, size=self.n_simulations)
        results = []
        for i in range(self.n_simulations):
            eff_T = max(Ts[i], 1e-6)
            eff_sigma = max(sigmas[i], 1e-6)
            S = (betas[i] * d_phis[i]) / (eff_T * eff_sigma)
            state = 1 if S > 1.0 else 0
            results.append([betas[i], d_phis[i], eff_T, eff_sigma, S, state])
        df = pd.DataFrame(results, columns=['beta', 'd_phi', 'T', 'sigma', 'S', 'state'])
        print(f"[PITON+] Sweep complete in {time.time() - start_time:.2f}s.")
        return df

    def extract_micro_laws(self, df):
        high_noise = df[df['sigma'] > 0.8]
        survival_rate = high_noise['state'].mean()
        high_tension = df[df['T'] > 0.8]
        saved_by_flux = high_tension[high_tension['d_phi'] > 2.0]
        rescue_rate = saved_by_flux['state'].mean()
        report = {
            "MicroLaw_Noise_Death_Zone": f"Survival Rate {survival_rate:.2%}",
            "MicroLaw_Flux_Rescue": f"Rescue Rate {rescue_rate:.2%}"
        }
        return report

if __name__ == "__main__":
    piton = PitonFalsifier(n_simulations=10000)
    data = piton.run_fractal_sweep()
    print(piton.extract_micro_laws(data))
