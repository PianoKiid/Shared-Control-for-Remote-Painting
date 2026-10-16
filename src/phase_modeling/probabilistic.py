"""Supervised GMM, HMM, GMM-HMM, and duration-HMM models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .data import PHASE_NAMES, TrainingData, transform_features
from .gmm import DiagonalGMM, fit_diagonal_gmm, logsumexp


MODEL_TYPES = {
    "gmm",
    "gaussian_hmm",
    "gmm_hmm",
    "gmm_hsmm",
    "calibrated_sticky_gmm_hmm",
}


def normalized_counts(counts: np.ndarray, pseudocount: float) -> np.ndarray:
    values = np.asarray(counts, dtype=np.float64) + pseudocount
    return values / values.sum(axis=-1, keepdims=True)


def transition_parameters(
    sequences: list[Any],
    pseudocount: float,
    allow_self: bool,
) -> tuple[np.ndarray, np.ndarray]:
    initial = np.zeros(4, dtype=np.float64)
    transition = np.zeros((4, 4), dtype=np.float64)
    for sequence in sequences:
        labels = np.asarray(sequence.labels, dtype=np.int8)
        initial[int(labels[0])] += 1
        for previous, current in zip(labels[:-1], labels[1:]):
            if allow_self or previous != current:
                transition[int(previous), int(current)] += 1
    initial = normalized_counts(initial, pseudocount)
    if allow_self:
        transition = normalized_counts(transition, pseudocount)
    else:
        transition += pseudocount
        np.fill_diagonal(transition, 0.0)
        row_sum = transition.sum(axis=1, keepdims=True)
        transition = np.divide(
            transition,
            row_sum,
            out=np.full_like(transition, 1.0 / 3.0),
            where=row_sum > 0,
        )
        np.fill_diagonal(transition, 0.0)
        transition /= transition.sum(axis=1, keepdims=True)
    return initial, transition


def collect_phase_durations(sequences: list[Any]) -> list[list[int]]:
    result: list[list[int]] = [[] for _ in range(4)]
    for sequence in sequences:
        labels = np.asarray(sequence.labels, dtype=np.int8)
        boundaries = np.r_[0, np.flatnonzero(labels[1:] != labels[:-1]) + 1, len(labels)]
        for start, stop in zip(boundaries[:-1], boundaries[1:]):
            result[int(labels[start])].append(int(stop - start))
    return result


def duration_hazards(
    durations: list[list[int]],
    age_cap_frames: int,
    smoothing: float,
) -> np.ndarray:
    cap = int(max(3, age_cap_frames))
    hazards = np.zeros((4, cap), dtype=np.float64)
    for phase in range(4):
        values = np.asarray(durations[phase], dtype=np.int64)
        if not len(values):
            raise ValueError(f"No duration observations for phase {phase}")
        for age_index in range(cap - 1):
            duration = age_index + 1
            at_risk = int(np.sum(values >= duration))
            endings = int(np.sum(values == duration))
            hazards[phase, age_index] = (endings + smoothing) / (
                at_risk + 2.0 * smoothing
            )
        tail = values[values >= cap] - cap + 1
        if len(tail):
            tail_hazard = 1.0 / max(1.0, float(np.mean(tail)))
        else:
            tail_hazard = float(hazards[phase, cap - 2])
        hazards[phase, cap - 1] = np.clip(tail_hazard, 1e-4, 0.95)
    return np.clip(hazards, 1e-6, 1.0 - 1e-6)


@dataclass
class PhaseModel:
    model_type: str
    scaler_mean: np.ndarray
    scaler_scale: np.ndarray
    class_prior: np.ndarray
    transition: np.ndarray
    mixture_weights: np.ndarray
    mixture_means: np.ndarray
    mixture_variances: np.ndarray
    feature_names: np.ndarray
    label_version: str
    metadata: dict[str, Any]
    duration_hazard: np.ndarray | None = None
    emission_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.model_type not in MODEL_TYPES:
            raise ValueError(f"Unknown model type: {self.model_type}")
        self._belief: np.ndarray | None = None
        self._age_belief: np.ndarray | None = None

    @property
    def components(self) -> int:
        return int(self.mixture_weights.shape[1])

    def reset(self) -> None:
        self._belief = None
        self._age_belief = None

    def transform(self, raw_feature: np.ndarray) -> np.ndarray:
        return transform_features(raw_feature, self.scaler_mean, self.scaler_scale)

    def emission_log_prob(self, normalized_features: np.ndarray) -> np.ndarray:
        values = np.atleast_2d(np.asarray(normalized_features, dtype=np.float64))
        result = np.empty((len(values), 4), dtype=np.float64)
        for phase in range(4):
            gmm = DiagonalGMM(
                self.mixture_weights[phase],
                self.mixture_means[phase],
                self.mixture_variances[phase],
            )
            result[:, phase] = gmm.score_samples(values)
        return result

    def _normalized_likelihood(self, normalized_feature: np.ndarray) -> np.ndarray:
        log_likelihood = self.emission_log_prob(np.asarray(normalized_feature)[None, :])[0]
        return np.exp(self.emission_scale * (log_likelihood - np.max(log_likelihood)))

    def step_normalized(self, normalized_feature: np.ndarray) -> tuple[int, np.ndarray]:
        likelihood = self._normalized_likelihood(normalized_feature)
        if self.model_type == "gmm":
            posterior = self.class_prior * likelihood
            posterior /= posterior.sum()
            return int(np.argmax(posterior)), posterior

        if self.model_type in {"gaussian_hmm", "gmm_hmm", "calibrated_sticky_gmm_hmm"}:
            predicted = self.class_prior if self._belief is None else self._belief @ self.transition
            posterior = predicted * likelihood
            posterior /= posterior.sum()
            self._belief = posterior
            return int(np.argmax(posterior)), posterior

        if self.duration_hazard is None:
            raise ValueError("GMM-HSMM model is missing duration hazards")
        cap = self.duration_hazard.shape[1]
        if self._age_belief is None:
            age_belief = np.zeros((4, cap), dtype=np.float64)
            age_belief[:, 0] = self.class_prior
        else:
            previous = self._age_belief
            stay = previous * (1.0 - self.duration_hazard)
            exit_mass = np.sum(previous * self.duration_hazard, axis=1)
            age_belief = np.zeros_like(previous)
            age_belief[:, 1:] = stay[:, :-1]
            age_belief[:, -1] += stay[:, -1]
            age_belief[:, 0] = exit_mass @ self.transition
        age_belief *= likelihood[:, None]
        total = float(age_belief.sum())
        if total <= 0 or not np.isfinite(total):
            age_belief.fill(0.0)
            age_belief[:, 0] = self.class_prior
            age_belief *= likelihood[:, None]
            total = float(age_belief.sum())
        age_belief /= total
        self._age_belief = age_belief
        posterior = age_belief.sum(axis=1)
        return int(np.argmax(posterior)), posterior

    def step(self, raw_feature: np.ndarray) -> tuple[int, np.ndarray]:
        return self.step_normalized(self.transform(raw_feature))

    def predict_normalized_sequence(self, normalized_features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.reset()
        predictions = np.empty(len(normalized_features), dtype=np.int8)
        probabilities = np.empty((len(normalized_features), 4), dtype=np.float64)
        for index, feature in enumerate(normalized_features):
            predictions[index], probabilities[index] = self.step_normalized(feature)
        return predictions, probabilities

    def predict_sequence(self, raw_features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        normalized = transform_features(raw_features, self.scaler_mean, self.scaler_scale)
        return self.predict_normalized_sequence(normalized)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        duration = self.duration_hazard if self.duration_hazard is not None else np.empty((0, 0))
        np.savez_compressed(
            path,
            model_type=np.array(self.model_type),
            scaler_mean=self.scaler_mean,
            scaler_scale=self.scaler_scale,
            class_prior=self.class_prior,
            transition=self.transition,
            mixture_weights=self.mixture_weights,
            mixture_means=self.mixture_means,
            mixture_variances=self.mixture_variances,
            duration_hazard=duration,
            emission_scale=np.array(self.emission_scale),
            feature_names=self.feature_names,
            phase_names=PHASE_NAMES,
            label_version=np.array(self.label_version),
            metadata_json=np.array(json.dumps(self.metadata, ensure_ascii=False)),
        )


def fit_probabilistic_model(
    model_type: str,
    data: TrainingData,
    components: int = 3,
    seed: int = 0,
    maximum_iterations: int = 100,
    tolerance: float = 1e-4,
    covariance_floor: float = 1e-3,
    transition_pseudocount: float = 0.1,
    hsmm_age_cap_frames: int = 300,
    duration_smoothing: float = 0.5,
    emission_scale: float = 1.0,
    sticky_strength: float = 0.0,
) -> PhaseModel:
    if model_type not in MODEL_TYPES:
        raise ValueError(f"model_type must be one of {sorted(MODEL_TYPES)}")
    if model_type == "gaussian_hmm":
        components = 1
    values = data.features
    labels = data.labels
    fitted: list[DiagonalGMM] = []
    for phase in range(4):
        fitted.append(
            fit_diagonal_gmm(
                values[labels == phase],
                components=components,
                seed=seed + phase,
                maximum_iterations=maximum_iterations,
                tolerance=tolerance,
                covariance_floor=covariance_floor,
            )
        )
    weights = np.stack([model.weights for model in fitted])
    means = np.stack([model.means for model in fitted])
    variances = np.stack([model.variances for model in fitted])
    class_counts = np.bincount(labels, minlength=4).astype(np.float64)

    if model_type == "gmm_hsmm":
        initial, transition = transition_parameters(
            data.sequences, transition_pseudocount, allow_self=False
        )
        durations = collect_phase_durations(data.sequences)
        hazard = duration_hazards(durations, hsmm_age_cap_frames, duration_smoothing)
    else:
        initial, transition = transition_parameters(
            data.sequences, transition_pseudocount, allow_self=True
        )
        hazard = None
    if model_type == "calibrated_sticky_gmm_hmm":
        if not 0.0 <= sticky_strength < 1.0:
            raise ValueError("sticky_strength must be in [0, 1)")
        transition = (1.0 - sticky_strength) * transition + sticky_strength * np.eye(4)
        transition /= transition.sum(axis=1, keepdims=True)
    if model_type == "gmm":
        initial = normalized_counts(class_counts, transition_pseudocount)

    metadata: dict[str, Any] = {
        "components_per_phase": components,
        "training_samples": int(len(values)),
        "training_sequences": len(data.sequences),
        "phase_sample_counts": class_counts.astype(int).tolist(),
        "gmm_converged": [model.converged for model in fitted],
        "gmm_iterations": [model.iterations for model in fitted],
        "gmm_average_log_likelihood": [model.average_log_likelihood for model in fitted],
        "transition_pseudocount": transition_pseudocount,
        "covariance_type": "diagonal",
        "covariance_floor": covariance_floor,
        "online_inference": "framewise" if model_type == "gmm" else "causal_forward_filter",
        "emission_scale": emission_scale,
        "sticky_strength": sticky_strength,
    }
    if hazard is not None:
        durations = collect_phase_durations(data.sequences)
        metadata.update(
            {
                "hsmm_age_cap_frames": hsmm_age_cap_frames,
                "duration_smoothing": duration_smoothing,
                "phase_duration_interval_counts": [len(values) for values in durations],
                "phase_duration_mean_frames": [float(np.mean(values)) for values in durations],
                "hsmm_tail_age_bin": "age greater than or equal to cap; geometric learned tail",
            }
        )
    return PhaseModel(
        model_type=model_type,
        scaler_mean=data.scaler_mean,
        scaler_scale=data.scaler_scale,
        class_prior=initial,
        transition=transition,
        mixture_weights=weights,
        mixture_means=means,
        mixture_variances=variances,
        feature_names=data.feature_names,
        label_version=data.label_version,
        metadata=metadata,
        duration_hazard=hazard,
        emission_scale=emission_scale,
    )


def load_phase_model(path: Path) -> PhaseModel:
    with np.load(path) as values:
        duration = np.asarray(values["duration_hazard"], dtype=np.float64)
        return PhaseModel(
            model_type=str(values["model_type"]),
            scaler_mean=np.asarray(values["scaler_mean"], dtype=np.float64),
            scaler_scale=np.asarray(values["scaler_scale"], dtype=np.float64),
            class_prior=np.asarray(values["class_prior"], dtype=np.float64),
            transition=np.asarray(values["transition"], dtype=np.float64),
            mixture_weights=np.asarray(values["mixture_weights"], dtype=np.float64),
            mixture_means=np.asarray(values["mixture_means"], dtype=np.float64),
            mixture_variances=np.asarray(values["mixture_variances"], dtype=np.float64),
            duration_hazard=duration if duration.size else None,
            emission_scale=(
                float(values["emission_scale"])
                if "emission_scale" in values.files
                else 1.0
            ),
            feature_names=np.asarray(values["feature_names"]),
            label_version=str(values["label_version"]),
            metadata=json.loads(str(values["metadata_json"])),
        )
