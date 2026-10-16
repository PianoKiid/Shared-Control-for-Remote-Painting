"""A calibrated, causal finite-state-machine baseline.

This baseline is intentionally simple. It uses force magnitude for contact so an
occasional sign reversal of Fz does not invert the contact decision. Thresholds,
the approach direction, and retract duration are estimated only from training
trials.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .data import PHASE_NAMES, TrainingData


def balanced_accuracy(labels: np.ndarray, decisions: np.ndarray) -> float:
    positive = np.asarray(labels, dtype=bool)
    predicted = np.asarray(decisions, dtype=bool)
    sensitivity = float(np.mean(predicted[positive])) if np.any(positive) else 0.0
    specificity = float(np.mean(~predicted[~positive])) if np.any(~positive) else 0.0
    return 0.5 * (sensitivity + specificity)


def fit_binary_threshold(scores: np.ndarray, positive: np.ndarray) -> tuple[float, float]:
    values = np.asarray(scores, dtype=np.float64)
    targets = np.asarray(positive, dtype=bool)
    if not np.any(targets) or not np.any(~targets):
        raise ValueError("Threshold fitting needs positive and negative samples")
    quantiles = np.linspace(0.0, 1.0, 257)
    candidates = np.unique(np.quantile(values, quantiles))
    best_threshold = float(candidates[0])
    best_score = -np.inf
    for threshold in candidates:
        score = balanced_accuracy(targets, values >= threshold)
        if score > best_score:
            best_threshold = float(threshold)
            best_score = score
    return best_threshold, float(best_score)


@dataclass
class CausalFSMModel:
    contact_on_threshold_n: float
    contact_off_threshold_n: float
    motion_threshold_m_s: float
    approach_axis: np.ndarray
    approach_projection_threshold_m_s: float
    retract_max_frames: int
    feature_names: np.ndarray
    label_version: str
    metadata: dict[str, Any]

    model_type: str = "causal_fsm"

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._state = 0
        self._contact = False
        self._retract_age = 0

    def step(self, raw_feature: np.ndarray) -> tuple[int, np.ndarray]:
        feature = np.asarray(raw_feature, dtype=np.float64)
        force_magnitude = float(np.linalg.norm(feature[:3]))
        velocity = feature[6:9]
        speed = float(np.linalg.norm(velocity))
        projection = float(velocity @ self.approach_axis)

        if self._contact:
            self._contact = force_magnitude >= self.contact_off_threshold_n
        else:
            self._contact = force_magnitude >= self.contact_on_threshold_n

        if self._contact:
            state = 2
            self._retract_age = 0
        elif self._state == 2:
            state = 3
            self._retract_age = 1
        elif self._state == 3 and self._retract_age < self.retract_max_frames:
            state = 3
            self._retract_age += 1
        elif speed >= self.motion_threshold_m_s and projection >= self.approach_projection_threshold_m_s:
            state = 1
            self._retract_age = 0
        else:
            state = 0
            self._retract_age = 0

        self._state = state
        probability = np.zeros(4, dtype=np.float64)
        probability[state] = 1.0
        return state, probability

    def predict_sequence(self, raw_features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.reset()
        predictions = np.empty(len(raw_features), dtype=np.int8)
        probabilities = np.empty((len(raw_features), 4), dtype=np.float64)
        for index, feature in enumerate(raw_features):
            predictions[index], probabilities[index] = self.step(feature)
        return predictions, probabilities

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            model_type=np.array(self.model_type),
            contact_on_threshold_n=np.array(self.contact_on_threshold_n),
            contact_off_threshold_n=np.array(self.contact_off_threshold_n),
            motion_threshold_m_s=np.array(self.motion_threshold_m_s),
            approach_axis=self.approach_axis,
            approach_projection_threshold_m_s=np.array(self.approach_projection_threshold_m_s),
            retract_max_frames=np.array(self.retract_max_frames),
            feature_names=self.feature_names,
            phase_names=PHASE_NAMES,
            label_version=np.array(self.label_version),
            metadata_json=np.array(json.dumps(self.metadata, ensure_ascii=False)),
        )


def fit_causal_fsm(data: TrainingData) -> CausalFSMModel:
    normalized = data.features
    raw = normalized * data.scaler_scale + data.scaler_mean
    labels = data.labels
    force_magnitude = np.linalg.norm(raw[:, :3], axis=1)
    speed = np.linalg.norm(raw[:, 6:9], axis=1)

    contact_on, contact_fit = fit_binary_threshold(force_magnitude, labels == 2)
    painting_force = force_magnitude[labels == 2]
    contact_off = float(min(contact_on, np.quantile(painting_force, 0.10)))

    motion_target = np.isin(labels, [1, 3])
    motion_threshold, motion_fit = fit_binary_threshold(speed, motion_target)

    approach_velocity = raw[labels == 1, 6:9]
    retract_velocity = raw[labels == 3, 6:9]
    direction = np.mean(approach_velocity, axis=0) - np.mean(retract_velocity, axis=0)
    norm = float(np.linalg.norm(direction))
    if norm < 1e-9:
        direction = np.array([0.0, 0.0, 1.0])
    else:
        direction /= norm
    projection = raw[:, 6:9] @ direction
    approach_projection_threshold, approach_fit = fit_binary_threshold(
        projection[labels != 2], labels[labels != 2] == 1
    )

    retract_lengths: list[int] = []
    for sequence in data.sequences:
        phase = np.asarray(sequence.labels)
        padded = np.r_[False, phase == 3, False].astype(np.int8)
        boundaries = np.flatnonzero(np.diff(padded))
        retract_lengths.extend((boundaries[1::2] - boundaries[::2]).astype(int).tolist())
    retract_max = max(1, int(np.ceil(np.quantile(retract_lengths, 0.90))))

    metadata = {
        "training_samples": int(len(raw)),
        "training_sequences": len(data.sequences),
        "phase_sample_counts": np.bincount(labels, minlength=4).astype(int).tolist(),
        "contact_score": "Euclidean norm of Fx, Fy, Fz; invariant to Fz sign reversal",
        "contact_threshold_training_balanced_accuracy": contact_fit,
        "motion_threshold_training_balanced_accuracy": motion_fit,
        "approach_projection_training_balanced_accuracy": approach_fit,
        "retract_duration_quantile": 0.90,
        "online_inference": "deterministic causal state update",
    }
    return CausalFSMModel(
        contact_on_threshold_n=contact_on,
        contact_off_threshold_n=contact_off,
        motion_threshold_m_s=motion_threshold,
        approach_axis=direction,
        approach_projection_threshold_m_s=approach_projection_threshold,
        retract_max_frames=retract_max,
        feature_names=data.feature_names,
        label_version=data.label_version,
        metadata=metadata,
    )


def load_causal_fsm(path: Path) -> CausalFSMModel:
    with np.load(path) as values:
        return CausalFSMModel(
            contact_on_threshold_n=float(values["contact_on_threshold_n"]),
            contact_off_threshold_n=float(values["contact_off_threshold_n"]),
            motion_threshold_m_s=float(values["motion_threshold_m_s"]),
            approach_axis=np.asarray(values["approach_axis"], dtype=np.float64),
            approach_projection_threshold_m_s=float(values["approach_projection_threshold_m_s"]),
            retract_max_frames=int(values["retract_max_frames"]),
            feature_names=np.asarray(values["feature_names"]),
            label_version=str(values["label_version"]),
            metadata=json.loads(str(values["metadata_json"])),
        )
