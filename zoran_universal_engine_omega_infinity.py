#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime
import json, hashlib
from dataclasses import dataclass

DOI = "https://zenodo.org/records/17852766"
ENGINE_VERSION = "Ω∞-1.0"

@dataclass
class CoherenceInput:
    beta: float
    delta_c: float
    lambda_noise: float

class ZoranEngine:
    def __init__(self):
        self.doi = DOI
        self.version = ENGINE_VERSION

    def compute_S(self, ci: CoherenceInput) -> float:
        if ci.lambda_noise <= 0:
            raise ValueError("λ must be > 0")
        return (ci.beta * ci.delta_c) / ci.lambda_noise

    def generate_law(self, name: str, ci: CoherenceInput) -> dict:
        S = self.compute_S(ci)
        return {
            "law_name": name,
            "S_value": S,
            "DOI": self.doi,
            "authors": ["Frédéric Tabary", "Stéphanie Cartier"],
            "engine_version": self.version,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def analyze_material(self, properties: dict) -> dict:
        beta = properties.get("intention_alignment", 1.0)
        delta_c = (properties.get("cohesion", 0.0) + properties.get("resilience", 0.0)) / 2
        lambda_noise = max(0.0001, 1 - properties.get("entropy_resistance", 0))
        ci = CoherenceInput(beta, delta_c, lambda_noise)
        S = self.compute_S(ci)
        classification = "material_regenerative" if S > 1 else "material_degenerative"
        return {
            "material_classification": classification,
            "S_metric": S,
            "DOI": self.doi,
            "validated_by": ["Frédéric Tabary", "Stéphanie Cartier"],
            "engine_version": self.version,
            "timestamp": datetime.utcnow().isoformat()
        }

    def export_manifest(self, data: dict) -> dict:
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        sha = hashlib.sha512(payload).hexdigest()
        return {
            "doi": self.doi,
            "engine_version": self.version,
            "sha512": sha,
            "data": data,
            "authors": ["Frédéric Tabary", "Stéphanie Cartier"],
            "timestamp": datetime.utcnow().isoformat()
        }

if __name__ == "__main__":
    eng = ZoranEngine()
    ci = CoherenceInput(beta=1.2, delta_c=0.9, lambda_noise=0.4)
    law = eng.generate_law("Loi Démonstrative", ci)
    manifest = eng.export_manifest(law)
    material = eng.analyze_material({
        "cohesion": 0.82,
        "resilience": 0.76,
        "entropy_resistance": 0.44,
        "intention_alignment": 1.05
    })
    print(json.dumps({"law":law,"manifest":manifest,"material":material}, indent=4))
