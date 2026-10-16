"""Dataset loading and training-only standardization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


PHASE_NAMES = np.array(["FREE_MOTION", "APPROACH", "PAINTING", "RETRACT"])
FEATURE_NAMES = np.array(
    [
        "force_x_tcp_causal_N",
        "force_y_tcp_causal_N",
        "force_z_tcp_causal_N",
        "position_x_relative_trial_start_m",
        "position_y_relative_trial_start_m",
        "position_z_relative_trial_start_m",
        "velocity_x_base_causal_m_s",
        "velocity_y_base_causal_m_s",
        "velocity_z_base_causal_m_s",
        "acceleration_x_base_causal_m_s2",
        "acceleration_y_base_causal_m_s2",
        "acceleration_z_base_causal_m_s2",
    ]
)


@dataclass
class SequenceData:
    trial_slug: str
    segment_id: int
    features: np.ndarray
    labels: np.ndarray
    stamps_ns: np.ndarray


@dataclass
class TrainingData:
    sequences: list[SequenceData]
    scaler_mean: np.ndarray
    scaler_scale: np.ndarray
    feature_names: np.ndarray
    phase_names: np.ndarray
    label_version: str

    @property
    def features(self) -> np.ndarray:
        return np.concatenate([sequence.features for sequence in self.sequences], axis=0)

    @property
    def labels(self) -> np.ndarray:
        return np.concatenate([sequence.labels for sequence in self.sequences], axis=0)


def contiguous_true_runs(mask: np.ndarray) -> list[slice]:
    padded = np.r_[False, np.asarray(mask, dtype=bool), False].astype(np.int8)
    boundaries = np.flatnonzero(np.diff(padded))
    return [slice(int(start), int(stop)) for start, stop in zip(boundaries[::2], boundaries[1::2])]


def available_trials(data_root: Path) -> list[str]:
    return sorted(path.stem for path in (data_root / "trials").glob("*.npz"))


def load_raw_sequences(data_root: Path, trial_slugs: list[str]) -> tuple[list[SequenceData], np.ndarray, str]:
    sequences: list[SequenceData] = []
    expected_names: np.ndarray | None = None
    label_version: str | None = None
    for slug in trial_slugs:
        path = data_root / "trials" / f"{slug}.npz"
        if not path.exists():
            raise FileNotFoundError(f"Unknown trial: {slug} ({path})")
        with np.load(path) as trial:
            features = np.asarray(trial["feature_matrix"], dtype=np.float64)
            labels = np.asarray(trial["phase_id"], dtype=np.int8)
            stamps = np.asarray(trial["stamp_ns"], dtype=np.int64)
            valid = np.asarray(trial["feature_valid"], dtype=bool)
            lengths = np.asarray(trial["segment_lengths"], dtype=np.int64)
            segment_ids = np.asarray(trial["segment_ids"], dtype=np.int32)
            names = np.asarray(trial["feature_names"])
            current_label_version = str(trial["label_version"])
        if expected_names is None:
            expected_names = names
        elif not np.array_equal(expected_names, names):
            raise ValueError(f"Feature-name mismatch in {path}")
        if label_version is None:
            label_version = current_label_version
        elif label_version != current_label_version:
            raise ValueError(f"Label-version mismatch in {path}")
        if features.shape != (len(labels), 12):
            raise ValueError(f"Expected an N x 12 feature matrix in {path}")
        offset = 0
        for length, segment_id in zip(lengths, segment_ids):
            stop = offset + int(length)
            segment_valid = valid[offset:stop]
            for run_index, valid_slice in enumerate(contiguous_true_runs(segment_valid), 1):
                start = offset + int(valid_slice.start)
                run_stop = offset + int(valid_slice.stop)
                if run_stop - start < 2:
                    continue
                sequences.append(
                    SequenceData(
                        trial_slug=slug,
                        segment_id=int(segment_id) * 100 + run_index,
                        features=features[start:run_stop].copy(),
                        labels=labels[start:run_stop].copy(),
                        stamps_ns=stamps[start:run_stop].copy(),
                    )
                )
            offset = stop
        if offset != len(features):
            raise ValueError(f"Segment lengths do not cover {path}")
    if not sequences or expected_names is None or label_version is None:
        raise ValueError("No valid training sequences were loaded")
    return sequences, expected_names, label_version


def fit_scaler(sequences: list[SequenceData]) -> tuple[np.ndarray, np.ndarray]:
    values = np.concatenate([sequence.features for sequence in sequences], axis=0)
    mean = np.mean(values, axis=0)
    scale = np.std(values, axis=0)
    scale = np.where(scale < 1e-8, 1.0, scale)
    return mean, scale


def load_training_data(data_root: Path, trial_slugs: list[str]) -> TrainingData:
    sequences, feature_names, label_version = load_raw_sequences(data_root, trial_slugs)
    mean, scale = fit_scaler(sequences)
    normalized = [
        SequenceData(
            trial_slug=sequence.trial_slug,
            segment_id=sequence.segment_id,
            features=(sequence.features - mean) / scale,
            labels=sequence.labels,
            stamps_ns=sequence.stamps_ns,
        )
        for sequence in sequences
    ]
    labels = np.concatenate([sequence.labels for sequence in normalized])
    missing = sorted(set(range(4)) - set(map(int, np.unique(labels))))
    if missing:
        raise ValueError(f"Training trials contain no valid samples for phases: {missing}")
    return TrainingData(
        sequences=normalized,
        scaler_mean=mean,
        scaler_scale=scale,
        feature_names=feature_names,
        phase_names=PHASE_NAMES.copy(),
        label_version=label_version,
    )


def transform_features(features: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return (np.asarray(features, dtype=np.float64) - mean) / scale
