"""Original trained causal LSTM, evaluated with NumPy (no Torch in Isaac)."""

import numpy as np
from .features import FEATURE_NAMES


class PhaseLSTM:
    def __init__(self, path):
        with np.load(path, allow_pickle=False) as z:
            if str(z["model_type"]) != "causal_lstm" or int(z["layers"]) != 1:
                raise ValueError(
                    "Expected the project single-layer causal LSTM checkpoint"
                )
            if list(z["phase_names"]) != [
                "FREE_MOTION",
                "APPROACH",
                "PAINTING",
                "RETRACT",
            ]:
                raise ValueError("Checkpoint phase order differs")
            self.mean = z["scaler_mean"].copy()
            self.scale = z["scaler_scale"].copy()
            self.size = int(z["hidden_size"])
            self.weights = {
                str(k): z[f"state_{i}"].copy() for i, k in enumerate(z["state_keys"])
            }
            self.feature_names = list(z["feature_names"])
        if (
            len(self.mean) != 12
            or not np.all(np.isfinite(self.scale))
            or np.any(self.scale <= 0)
        ):
            raise ValueError("Invalid feature scaler")
        if self.feature_names != list(FEATURE_NAMES):
            raise ValueError("Checkpoint feature order differs from the live extractor")
        self.reset()

    def reset(self):
        self.h = np.zeros(self.size, np.float32)
        self.c = self.h.copy()

    def step(self, feature):
        x = np.asarray(feature, dtype=np.float64)
        if x.shape != (12,) or not np.isfinite(x).all():
            raise ValueError("Expected 12 finite features")
        x = ((x - self.mean) / self.scale).astype(np.float32)
        w = self.weights
        gates = (
            w["lstm.weight_ih_l0"] @ x
            + w["lstm.bias_ih_l0"]
            + w["lstm.weight_hh_l0"] @ self.h
            + w["lstm.bias_hh_l0"]
        )
        i, f, g, o = np.split(gates, 4)
        sigmoid = lambda v: 1 / (1 + np.exp(-np.clip(v, -80, 80)))
        self.c = sigmoid(f) * self.c + sigmoid(i) * np.tanh(g)
        self.h = sigmoid(o) * np.tanh(self.c)
        logits = w["classifier.weight"] @ self.h + w["classifier.bias"]
        exp = np.exp(logits - np.max(logits))
        return (exp / exp.sum()).astype(float)
