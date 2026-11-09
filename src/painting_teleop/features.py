"""Streaming reconstruction of phase_model_inputs_v1's 12 causal features.

Only the current/past supplied observations are used. This does not make a
noncausal upstream sensor synchronizer causal. Feed the recorded signed force [N],
BASE position [m], and integer nanosecond timestamps. By default the first
observation supplies the trial force zero and position reference. For a cropped
recording, pass those references from the FIRST observation of the full trial.

The feature names retain the original dataset's tcp suffix. In the supplied
recordings their numeric force convention follows the FT frame; the simulator
adapter performs that conversion before calling this module. This reconstruction
was reused from the project's 13_vs causal-feature audit (09_03/06_01 checks).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

FEATURE_NAMES = np.asarray(
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


@dataclass(frozen=True)
class FeatureFrame:
    features: np.ndarray
    valid: bool
    reset: bool
    dt_s: float
    force_zeroed_N: np.ndarray
    force_clean_N: np.ndarray
    outlier_mask: np.ndarray
    hard_limit_mask: np.ndarray


class CausalFeatureExtractor:
    """Stateful 12D feature transform; call reset() at segment boundaries.

    reset() preserves full-trial zero/reference. reset(new_trial=True) clears
    them so the next observation establishes a new trial. A gap >0.2 s or a
    nonincreasing timestamp resets filters automatically. A reset restarts the
    0.5 s warmup; consumers must reset their LSTM and wait for valid=True.
    """

    def __init__(self, *, force_offset_tcp_N=None, position_reference_base_m=None):
        self.force_offset_tcp_N = self._optional_vector(force_offset_tcp_N)
        self.position_reference_base_m = self._optional_vector(
            position_reference_base_m
        )
        self.reset()

    @staticmethod
    def _optional_vector(value):
        if value is None:
            return None
        result = np.asarray(value, dtype=np.float64).copy()
        if result.shape != (3,) or not np.all(np.isfinite(result)):
            raise ValueError("Reference must contain three finite values")
        return result

    def reset(self, *, new_trial=False):
        if new_trial:
            self.force_offset_tcp_N = None
            self.position_reference_base_m = None
        self._history = deque(maxlen=7)
        self._last_stamp_ns = None
        self._origin_ns = None
        self._last_local_time = 0.0
        self._last_position = None
        self._last_clean_force = np.zeros(3, dtype=np.float64)
        self._force_ema = np.zeros(3, dtype=np.float64)
        self._velocity = np.zeros(3, dtype=np.float64)
        self._acceleration = np.zeros(3, dtype=np.float64)

    def step(self, force_tcp_N, position_base_m, stamp_ns: int) -> FeatureFrame:
        force = np.asarray(force_tcp_N, dtype=np.float64)
        position = np.asarray(position_base_m, dtype=np.float64)
        if force.shape != (3,) or position.shape != (3,):
            raise ValueError("force_tcp_N and position_base_m must have shape (3,)")
        if not np.all(np.isfinite(position)):
            self.reset()
            raise ValueError("Nonfinite position: filter reset; observation rejected")
        if not isinstance(stamp_ns, (int, np.integer)):
            raise TypeError("stamp_ns must be an integer nanosecond timestamp")
        stamp_ns = int(stamp_ns)
        if self.force_offset_tcp_N is None:
            if not np.all(np.isfinite(force)):
                raise ValueError("A finite initial force is needed for trial zeroing")
            self.force_offset_tcp_N = force.copy()
        if self.position_reference_base_m is None:
            self.position_reference_base_m = position.copy()
        if self._last_stamp_ns is not None:
            gap = (stamp_ns - self._last_stamp_ns) / 1e9
            if gap <= 0.0 or gap > 0.2:
                self.reset()
        is_reset = self._last_stamp_ns is None
        if is_reset:
            self._origin_ns = stamp_ns
        local_time = (stamp_ns - self._origin_ns) / 1e9
        # Subtract relative times to reproduce the saved preprocessing arithmetic.
        dt = 0.0 if is_reset else local_time - self._last_local_time
        zeroed = force - self.force_offset_tcp_N
        hard = ~np.isfinite(zeroed) | (np.abs(zeroed) > 150.0)
        clean = zeroed.copy()
        clean[hard] = self._last_clean_force[hard]
        history_value = clean.copy()
        outlier = np.zeros(3, dtype=bool)
        if len(self._history) >= 3:
            history = np.asarray(self._history)
            median = np.median(history, axis=0)
            mad = np.median(np.abs(history - median), axis=0)
            threshold = np.maximum(10.0, 4.5 * 1.4826 * mad)
            outlier = np.abs(clean - median) > threshold
            clean[outlier] = median[outlier]
        self._history.append(history_value)
        if is_reset:
            self._force_ema = clean.copy()
        else:
            self._force_ema += (1.0 - np.exp(-dt / 0.12)) * (clean - self._force_ema)
            raw_velocity = (position - self._last_position) / dt
            previous_velocity = self._velocity.copy()
            self._velocity += (1.0 - np.exp(-dt / 0.10)) * (
                raw_velocity - self._velocity
            )
            raw_acceleration = (self._velocity - previous_velocity) / dt
            self._acceleration += (1.0 - np.exp(-dt / 0.15)) * (
                raw_acceleration - self._acceleration
            )
        features = np.concatenate(
            [
                self._force_ema,
                position - self.position_reference_base_m,
                self._velocity,
                self._acceleration,
            ]
        )
        self._last_position = position.copy()
        self._last_stamp_ns = stamp_ns
        self._last_local_time = local_time
        self._last_clean_force = clean.copy()
        return FeatureFrame(
            features,
            local_time >= 0.5,
            is_reset,
            dt,
            zeroed.copy(),
            clean.copy(),
            outlier.copy(),
            hard.copy(),
        )


def replay_features(
    stamp_ns,
    force_tcp_N,
    position_base_m,
    *,
    segment_id=None,
    force_offset_tcp_N=None,
    position_reference_base_m=None,
):
    """Convenience adapter that calls the same online step once per observation."""
    stamps = np.asarray(stamp_ns)
    forces = np.asarray(force_tcp_N)
    positions = np.asarray(position_base_m)
    n = len(stamps)
    if forces.shape != (n, 3) or positions.shape != (n, 3):
        raise ValueError("Input lengths/shapes differ")
    segments = (
        np.ones(n, dtype=np.int32) if segment_id is None else np.asarray(segment_id)
    )
    if segments.shape != (n,):
        raise ValueError("segment_id must have one value per observation")
    extractor = CausalFeatureExtractor(
        force_offset_tcp_N=force_offset_tcp_N,
        position_reference_base_m=position_reference_base_m,
    )
    result = {
        "feature_matrix": np.empty((n, 12), dtype=np.float64),
        "feature_valid": np.zeros(n, dtype=bool),
        "filter_reset_mask": np.zeros(n, dtype=bool),
        "dt_s": np.zeros(n, dtype=np.float64),
        "force_tcp_zeroed_N": np.empty((n, 3), dtype=np.float64),
        "force_clean_N": np.empty((n, 3), dtype=np.float64),
        "force_causal_outlier_mask": np.zeros((n, 3), dtype=bool),
        "force_causal_hard_limit_mask": np.zeros((n, 3), dtype=bool),
    }
    for i in range(n):
        if i and segments[i] != segments[i - 1]:
            extractor.reset()
        frame = extractor.step(forces[i], positions[i], stamps[i])
        result["feature_matrix"][i] = frame.features
        result["feature_valid"][i] = frame.valid
        result["filter_reset_mask"][i] = frame.reset
        result["dt_s"][i] = frame.dt_s
        result["force_tcp_zeroed_N"][i] = frame.force_zeroed_N
        result["force_clean_N"][i] = frame.force_clean_N
        result["force_causal_outlier_mask"][i] = frame.outlier_mask
        result["force_causal_hard_limit_mask"][i] = frame.hard_limit_mask
    result["force_offset_tcp_N"] = extractor.force_offset_tcp_N
    result["trial_reference_position_base_m"] = extractor.position_reference_base_m
    result["feature_names"] = FEATURE_NAMES.copy()
    return result
