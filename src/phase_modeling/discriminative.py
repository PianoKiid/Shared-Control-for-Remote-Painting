"""Random-forest and causal-LSTM phase classifiers.

Both models expose the same reset/step/predict_sequence contract as the
probabilistic phase models so held-out evaluation is genuinely framewise.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DEPENDENCIES = PROJECT_ROOT / ".analysis_deps"
if LOCAL_DEPENDENCIES.exists() and str(LOCAL_DEPENDENCIES) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPENDENCIES))
TORCH_DLL_DIRECTORY = LOCAL_DEPENDENCIES / "torch" / "lib"
_torch_dll_handle = None
if sys.platform == "win32" and TORCH_DLL_DIRECTORY.exists():
    _torch_dll_handle = os.add_dll_directory(str(TORCH_DLL_DIRECTORY))

from sklearn.ensemble import RandomForestClassifier  # noqa: E402
import torch  # noqa: E402
from torch import nn  # noqa: E402

from .data import PHASE_NAMES, TrainingData, transform_features


DISCRIMINATIVE_MODEL_TYPES = {"random_forest", "causal_lstm"}
WEIGHTING_MODES = {"unweighted", "phase", "peri_transition"}
DEFAULT_PHASE_WEIGHTS = (1.44, 3.0, 1.0, 3.0)


def sequence_frame_weights(
    data: TrainingData,
    weighting_mode: str,
    phase_weights: Sequence[float] = DEFAULT_PHASE_WEIGHTS,
    peri_window_seconds: float = 1.0,
    peri_weight: float = 1.2,
    normal_weight: float = 0.6,
) -> list[np.ndarray]:
    """Return one loss/sample-weight vector for every training sequence."""
    if weighting_mode not in WEIGHTING_MODES:
        raise ValueError(f"weighting_mode must be one of {sorted(WEIGHTING_MODES)}")
    phase_values = np.asarray(phase_weights, dtype=np.float64)
    if phase_values.shape != (4,) or np.any(phase_values <= 0):
        raise ValueError("phase_weights must contain four positive values")
    if peri_window_seconds < 0 or peri_weight <= 0 or normal_weight <= 0:
        raise ValueError("peri window must be nonnegative and weights must be positive")
    results: list[np.ndarray] = []
    for sequence in data.sequences:
        if weighting_mode == "unweighted":
            weights = np.ones(len(sequence.labels), dtype=np.float64)
        elif weighting_mode == "phase":
            weights = phase_values[np.asarray(sequence.labels, dtype=np.int64)]
        else:
            weights = np.full(len(sequence.labels), normal_weight, dtype=np.float64)
            boundaries = np.flatnonzero(sequence.labels[1:] != sequence.labels[:-1]) + 1
            window_ns = int(peri_window_seconds * 1e9)
            for boundary in boundaries:
                stamp = int(sequence.stamps_ns[boundary])
                start = int(np.searchsorted(sequence.stamps_ns, stamp - window_ns, side="left"))
                stop = int(np.searchsorted(sequence.stamps_ns, stamp + window_ns, side="right"))
                weights[start:stop] = peri_weight
        results.append(weights)
    return results


@dataclass
class RandomForestPhaseModel:
    estimator: RandomForestClassifier
    scaler_mean: np.ndarray
    scaler_scale: np.ndarray
    feature_names: np.ndarray
    label_version: str
    metadata: dict[str, Any]
    model_type: str = "random_forest"

    def reset(self) -> None:
        return None

    def step(self, raw_feature: np.ndarray) -> tuple[int, np.ndarray]:
        normalized = transform_features(raw_feature, self.scaler_mean, self.scaler_scale)
        partial = self.estimator.predict_proba(np.asarray(normalized)[None, :])[0]
        probabilities = np.zeros(4, dtype=np.float64)
        probabilities[np.asarray(self.estimator.classes_, dtype=np.int64)] = partial
        return int(np.argmax(probabilities)), probabilities

    def predict_sequence(self, raw_features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.reset()
        normalized = transform_features(raw_features, self.scaler_mean, self.scaler_scale)
        partial = self.estimator.predict_proba(normalized)
        probabilities = np.zeros((len(normalized), 4), dtype=np.float64)
        probabilities[:, np.asarray(self.estimator.classes_, dtype=np.int64)] = partial
        predictions = np.argmax(probabilities, axis=1).astype(np.int8)
        return predictions, probabilities

    def save(self, path: Path) -> None:
        import pickle

        path.parent.mkdir(parents=True, exist_ok=True)
        estimator_bytes = np.frombuffer(
            pickle.dumps(self.estimator, protocol=pickle.HIGHEST_PROTOCOL), dtype=np.uint8
        )
        np.savez_compressed(
            path,
            model_type=np.array(self.model_type),
            estimator_pickle=estimator_bytes,
            scaler_mean=self.scaler_mean,
            scaler_scale=self.scaler_scale,
            feature_names=self.feature_names,
            phase_names=PHASE_NAMES,
            label_version=np.array(self.label_version),
            metadata_json=np.array(json.dumps(self.metadata, ensure_ascii=False)),
        )


class _CausalLSTMNetwork(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, layers: int) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=layers,
            batch_first=True,
        )
        self.classifier = nn.Linear(hidden_size, 4)

    def forward(
        self,
        values: torch.Tensor,
        hidden: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        encoded, next_hidden = self.lstm(values, hidden)
        return self.classifier(encoded), next_hidden


@dataclass
class CausalLSTMPhaseModel:
    network: _CausalLSTMNetwork
    scaler_mean: np.ndarray
    scaler_scale: np.ndarray
    feature_names: np.ndarray
    label_version: str
    metadata: dict[str, Any]
    hidden_size: int
    layers: int
    model_type: str = "causal_lstm"

    def __post_init__(self) -> None:
        self.network.to("cpu")
        self.network.eval()
        self._hidden: tuple[torch.Tensor, torch.Tensor] | None = None

    def reset(self) -> None:
        self._hidden = None

    def step(self, raw_feature: np.ndarray) -> tuple[int, np.ndarray]:
        normalized = transform_features(raw_feature, self.scaler_mean, self.scaler_scale)
        values = torch.as_tensor(normalized, dtype=torch.float32).reshape(1, 1, -1)
        with torch.inference_mode():
            logits, self._hidden = self.network(values, self._hidden)
            self._hidden = tuple(value.detach() for value in self._hidden)
            probabilities = torch.softmax(logits[0, -1], dim=-1).cpu().numpy().astype(np.float64)
        return int(np.argmax(probabilities)), probabilities

    def predict_sequence(self, raw_features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.reset()
        predictions = np.empty(len(raw_features), dtype=np.int8)
        probabilities = np.empty((len(raw_features), 4), dtype=np.float64)
        for index, feature in enumerate(raw_features):
            predictions[index], probabilities[index] = self.step(feature)
        return predictions, probabilities

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        state = self.network.state_dict()
        payload: dict[str, Any] = {
            "model_type": np.array(self.model_type),
            "scaler_mean": self.scaler_mean,
            "scaler_scale": self.scaler_scale,
            "feature_names": self.feature_names,
            "phase_names": PHASE_NAMES,
            "label_version": np.array(self.label_version),
            "metadata_json": np.array(json.dumps(self.metadata, ensure_ascii=False)),
            "hidden_size": np.array(self.hidden_size),
            "layers": np.array(self.layers),
            "state_keys": np.asarray(list(state), dtype=np.str_),
        }
        for index, value in enumerate(state.values()):
            payload[f"state_{index}"] = value.detach().cpu().numpy()
        np.savez_compressed(path, **payload)


def fit_random_forest(
    data: TrainingData,
    trees: int = 200,
    max_depth: int | None = 24,
    min_samples_leaf: int = 5,
    seed: int = 0,
    weighting_mode: str = "unweighted",
    phase_weights: Sequence[float] = DEFAULT_PHASE_WEIGHTS,
    peri_window_seconds: float = 1.0,
    peri_weight: float = 1.2,
    normal_weight: float = 0.6,
) -> RandomForestPhaseModel:
    estimator = RandomForestClassifier(
        n_estimators=trees,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        class_weight=None,
        random_state=seed,
        n_jobs=-1,
    )
    weights_by_sequence = sequence_frame_weights(
        data,
        weighting_mode,
        phase_weights,
        peri_window_seconds,
        peri_weight,
        normal_weight,
    )
    sample_weight = np.concatenate(weights_by_sequence)
    estimator.fit(data.features, data.labels, sample_weight=sample_weight)
    return RandomForestPhaseModel(
        estimator=estimator,
        scaler_mean=data.scaler_mean,
        scaler_scale=data.scaler_scale,
        feature_names=data.feature_names,
        label_version=data.label_version,
        metadata={
            "training_samples": int(len(data.labels)),
            "training_sequences": len(data.sequences),
            "phase_sample_counts": np.bincount(data.labels, minlength=4).astype(int).tolist(),
            "trees": trees,
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "class_weight": None,
            "weighting_mode": weighting_mode,
            "phase_weights": list(map(float, phase_weights)),
            "peri_window_seconds": peri_window_seconds,
            "peri_weight": peri_weight,
            "normal_weight": normal_weight,
            "training_weight_mean": float(np.mean(sample_weight)),
            "online_inference": "framewise current observation",
        },
    )


def _chunk_training_sequences(
    data: TrainingData,
    chunk_length: int,
    weights_by_sequence: list[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    feature_chunks: list[np.ndarray] = []
    label_chunks: list[np.ndarray] = []
    weight_chunks: list[np.ndarray] = []
    for sequence, sequence_weights in zip(data.sequences, weights_by_sequence):
        for start in range(0, len(sequence.labels), chunk_length):
            stop = min(start + chunk_length, len(sequence.labels))
            if stop - start < 2:
                continue
            features = np.zeros((chunk_length, sequence.features.shape[1]), dtype=np.float32)
            labels = np.full(chunk_length, -100, dtype=np.int64)
            weights = np.zeros(chunk_length, dtype=np.float32)
            length = stop - start
            features[:length] = sequence.features[start:stop]
            labels[:length] = sequence.labels[start:stop]
            weights[:length] = sequence_weights[start:stop]
            feature_chunks.append(features)
            label_chunks.append(labels)
            weight_chunks.append(weights)
    if not feature_chunks:
        raise ValueError("No LSTM training chunks were created")
    return np.stack(feature_chunks), np.stack(label_chunks), np.stack(weight_chunks)


def fit_causal_lstm(
    data: TrainingData,
    hidden_size: int = 64,
    layers: int = 1,
    chunk_length: int = 120,
    batch_size: int = 32,
    epochs: int = 20,
    learning_rate: float = 1e-3,
    seed: int = 0,
    weighting_mode: str = "unweighted",
    phase_weights: Sequence[float] = DEFAULT_PHASE_WEIGHTS,
    peri_window_seconds: float = 1.0,
    peri_weight: float = 1.2,
    normal_weight: float = 0.6,
    stateful_training: bool = False,
) -> CausalLSTMPhaseModel:
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    network = _CausalLSTMNetwork(data.features.shape[1], hidden_size, layers)
    optimizer = torch.optim.Adam(network.parameters(), lr=learning_rate)
    criterion = nn.CrossEntropyLoss(ignore_index=-100, reduction="none")
    weights_by_sequence = sequence_frame_weights(
        data,
        weighting_mode,
        phase_weights,
        peri_window_seconds,
        peri_weight,
        normal_weight,
    )
    rng = np.random.default_rng(seed)
    losses: list[float] = []
    network.train()
    for _ in range(epochs):
        total_loss = 0.0
        total_frames = 0
        if stateful_training:
            sequence_order = rng.permutation(len(data.sequences))
            for group_start in range(0, len(sequence_order), batch_size):
                group_indices = sequence_order[group_start : group_start + batch_size]
                group_sequences = [data.sequences[index] for index in group_indices]
                group_weights = [weights_by_sequence[index] for index in group_indices]
                hidden: tuple[torch.Tensor, torch.Tensor] | None = None
                maximum_length = max(len(sequence.labels) for sequence in group_sequences)
                for chunk_start in range(0, maximum_length, chunk_length):
                    batch_features = np.zeros(
                        (len(group_sequences), chunk_length, data.features.shape[1]),
                        dtype=np.float32,
                    )
                    batch_labels = np.full(
                        (len(group_sequences), chunk_length), -100, dtype=np.int64
                    )
                    batch_weights = np.zeros(
                        (len(group_sequences), chunk_length), dtype=np.float32
                    )
                    for row, (sequence, sequence_weights) in enumerate(
                        zip(group_sequences, group_weights)
                    ):
                        chunk_stop = min(chunk_start + chunk_length, len(sequence.labels))
                        length = chunk_stop - chunk_start
                        if length <= 0:
                            continue
                        batch_features[row, :length] = sequence.features[
                            chunk_start:chunk_stop
                        ]
                        batch_labels[row, :length] = sequence.labels[chunk_start:chunk_stop]
                        batch_weights[row, :length] = sequence_weights[chunk_start:chunk_stop]
                    feature_tensor = torch.from_numpy(batch_features)
                    label_tensor = torch.from_numpy(batch_labels)
                    weight_tensor = torch.from_numpy(batch_weights)
                    optimizer.zero_grad(set_to_none=True)
                    logits, next_hidden = network(feature_tensor, hidden)
                    frame_loss = criterion(
                        logits.reshape(-1, 4), label_tensor.reshape(-1)
                    ).reshape(label_tensor.shape)
                    loss = (frame_loss * weight_tensor).sum() / weight_tensor.sum().clamp_min(
                        1e-12
                    )
                    loss.backward()
                    nn.utils.clip_grad_norm_(network.parameters(), max_norm=5.0)
                    optimizer.step()
                    hidden = tuple(value.detach() for value in next_hidden)
                    valid_frames = int((label_tensor != -100).sum().item())
                    total_loss += float(loss.detach()) * valid_frames
                    total_frames += valid_frames
        else:
            features, labels, frame_weights = _chunk_training_sequences(
                data, chunk_length, weights_by_sequence
            )
            order = rng.permutation(len(features))
            for start in range(0, len(order), batch_size):
                indices = order[start : start + batch_size]
                batch_features = torch.from_numpy(features[indices])
                batch_labels = torch.from_numpy(labels[indices])
                batch_weights = torch.from_numpy(frame_weights[indices])
                optimizer.zero_grad(set_to_none=True)
                logits, _ = network(batch_features)
                frame_loss = criterion(
                    logits.reshape(-1, 4), batch_labels.reshape(-1)
                ).reshape(batch_labels.shape)
                loss = (frame_loss * batch_weights).sum() / batch_weights.sum().clamp_min(
                    1e-12
                )
                loss.backward()
                nn.utils.clip_grad_norm_(network.parameters(), max_norm=5.0)
                optimizer.step()
                valid_frames = int((batch_labels != -100).sum().item())
                total_loss += float(loss.detach()) * valid_frames
                total_frames += valid_frames
        losses.append(total_loss / max(total_frames, 1))
    network.eval()
    return CausalLSTMPhaseModel(
        network=network,
        scaler_mean=data.scaler_mean,
        scaler_scale=data.scaler_scale,
        feature_names=data.feature_names,
        label_version=data.label_version,
        metadata={
            "training_samples": int(len(data.labels)),
            "training_sequences": len(data.sequences),
            "phase_sample_counts": np.bincount(data.labels, minlength=4).astype(int).tolist(),
            "hidden_size": hidden_size,
            "layers": layers,
            "training_chunk_length": chunk_length,
            "training_batch_size": batch_size,
            "stateful_training": stateful_training,
            "stateful_training_detail": (
                "hidden state carried across chronological chunks within each sequence; "
                "detached at each chunk boundary"
                if stateful_training
                else "hidden state reset for every shuffled training chunk"
            ),
            "epochs": epochs,
            "learning_rate": learning_rate,
            "loss": "cross entropy with per-frame weights",
            "weighting_mode": weighting_mode,
            "phase_weights": list(map(float, phase_weights)),
            "peri_window_seconds": peri_window_seconds,
            "peri_weight": peri_weight,
            "normal_weight": normal_weight,
            "training_weight_mean": float(np.mean(np.concatenate(weights_by_sequence))),
            "epoch_losses": losses,
            "online_inference": "stateful causal LSTM, one observation per step",
        },
        hidden_size=hidden_size,
        layers=layers,
    )


def load_discriminative_model(path: Path) -> RandomForestPhaseModel | CausalLSTMPhaseModel:
    import pickle

    with np.load(path, allow_pickle=False) as values:
        model_type = str(values["model_type"])
        common = {
            "scaler_mean": np.asarray(values["scaler_mean"], dtype=np.float64),
            "scaler_scale": np.asarray(values["scaler_scale"], dtype=np.float64),
            "feature_names": np.asarray(values["feature_names"]),
            "label_version": str(values["label_version"]),
            "metadata": json.loads(str(values["metadata_json"])),
        }
        if model_type == "random_forest":
            estimator = pickle.loads(np.asarray(values["estimator_pickle"], dtype=np.uint8).tobytes())
            return RandomForestPhaseModel(estimator=estimator, **common)
        if model_type != "causal_lstm":
            raise ValueError(f"Unknown discriminative model type: {model_type}")
        hidden_size = int(values["hidden_size"])
        layers = int(values["layers"])
        network = _CausalLSTMNetwork(len(common["feature_names"]), hidden_size, layers)
        keys = [str(value) for value in values["state_keys"]]
        state = {
            key: torch.from_numpy(np.asarray(values[f"state_{index}"]))
            for index, key in enumerate(keys)
        }
        network.load_state_dict(state)
        return CausalLSTMPhaseModel(
            network=network,
            hidden_size=hidden_size,
            layers=layers,
            **common,
        )
