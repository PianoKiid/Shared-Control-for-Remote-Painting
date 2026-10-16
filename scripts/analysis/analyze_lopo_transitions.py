"""Analyze causal-LOPO phase predictions as shared-control switching signals.

The existing +/- tolerance metrics answer whether a predicted transition is
near a label boundary.  This analysis instead asks whether raw causal LSTM
outputs are suitable for directly switching painting assistance in real time.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DEPENDENCIES = PROJECT_ROOT / ".analysis_deps"
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if LOCAL_DEPENDENCIES.exists() and str(LOCAL_DEPENDENCIES) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPENDENCIES))

import torch  # noqa: E402

from phase_modeling.data import PHASE_NAMES, load_raw_sequences, transform_features  # noqa: E402
from phase_modeling.model_io import load_model  # noqa: E402


DATA_ROOT = PROJECT_ROOT / "data" / "processed" / "phase_model_inputs_v1"
MODEL_ROOT = (
    PROJECT_ROOT
    / "results"
    / "phase_learning"
    / "final_lopo"
    / "models"
    / "causal_lstm_all_folds"
)
OUTPUT_ROOT = (
    PROJECT_ROOT / "results" / "phase_learning" / "transition_aware_analysis"
)
PARTICIPANTS = ("06", "07", "08", "09", "10", "11")
STABLE_SECONDS = 0.15
PROFILE_OFFSETS_S = (-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0)


def scalar(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return None if not math.isfinite(value) else value
    return value


def stats(values) -> dict:
    array = np.asarray([float(v) for v in values if v is not None and math.isfinite(float(v))])
    if len(array) == 0:
        return {"n": 0, "mean": None, "sd": None, "median": None, "q1": None, "q3": None}
    return {
        "n": int(len(array)),
        "mean": float(np.mean(array)),
        "sd": float(np.std(array, ddof=1)) if len(array) > 1 else 0.0,
        "median": float(np.median(array)),
        "q1": float(np.quantile(array, 0.25)),
        "q3": float(np.quantile(array, 0.75)),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def runs(values: np.ndarray) -> list[tuple[int, int, int]]:
    """Return value runs as (start, stop-exclusive, value)."""
    values = np.asarray(values)
    if len(values) == 0:
        return []
    starts = np.r_[0, np.flatnonzero(values[1:] != values[:-1]) + 1]
    stops = np.r_[starts[1:], len(values)]
    return [(int(a), int(b), int(values[a])) for a, b in zip(starts, stops)]


def durations_per_frame(stamps_ns: np.ndarray) -> tuple[np.ndarray, float]:
    diffs = np.diff(stamps_ns).astype(np.float64) / 1e9
    positive = diffs[diffs > 0]
    median_dt = float(np.median(positive)) if len(positive) else 1.0 / 33.0
    dt = np.r_[diffs, median_dt]
    dt = np.where((dt > 0) & (dt < 0.25), dt, median_dt)
    return dt, median_dt


def fast_predict(model, features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    normalized = transform_features(features, model.scaler_mean, model.scaler_scale)
    values = torch.as_tensor(normalized, dtype=torch.float32).unsqueeze(0)
    model.reset()
    with torch.inference_mode():
        logits, _ = model.network(values)
        probabilities = torch.softmax(logits[0], dim=-1).cpu().numpy().astype(np.float64)
    predictions = np.argmax(probabilities, axis=1).astype(np.int8)
    return predictions, probabilities


def elapsed(stamps_ns: np.ndarray, start: int, stop: int, median_dt: float) -> float:
    if stop <= start:
        return 0.0
    return float((stamps_ns[stop - 1] - stamps_ns[start]) / 1e9 + median_dt)


def first_stable_target_delay(
    prediction: np.ndarray,
    stamps_ns: np.ndarray,
    start: int,
    stop: int,
    target: int,
    median_dt: float,
    minimum_seconds: float,
) -> float | None:
    """Delay to first target run lasting minimum_seconds inside [start, stop)."""
    for run_start, run_stop, value in runs(prediction[start:stop]):
        if value != target:
            continue
        absolute_start = start + run_start
        absolute_stop = start + run_stop
        if elapsed(stamps_ns, absolute_start, absolute_stop, median_dt) >= minimum_seconds:
            return float((stamps_ns[absolute_start] - stamps_ns[start]) / 1e9)
    return None


def continuous_duration_after(
    mask: np.ndarray, stamps_ns: np.ndarray, start: int, median_dt: float
) -> float:
    if start >= len(mask) or not bool(mask[start]):
        return 0.0
    stop = start + 1
    while stop < len(mask) and bool(mask[stop]):
        stop += 1
    return elapsed(stamps_ns, start, stop, median_dt)


def continuous_duration_before(
    mask: np.ndarray, stamps_ns: np.ndarray, stop: int, median_dt: float
) -> float:
    if stop <= 0 or not bool(mask[stop - 1]):
        return 0.0
    start = stop - 1
    while start > 0 and bool(mask[start - 1]):
        start -= 1
    return elapsed(stamps_ns, start, stop, median_dt)


def nearest_index(stamps_ns: np.ndarray, target_ns: int) -> int | None:
    index = int(np.searchsorted(stamps_ns, target_ns))
    choices = [candidate for candidate in (index - 1, index) if 0 <= candidate < len(stamps_ns)]
    if not choices:
        return None
    return min(choices, key=lambda candidate: abs(int(stamps_ns[candidate]) - target_ns))


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    trial_paths = sorted((DATA_ROOT / "trials").glob("*.npz"))
    trial_slugs = [path.stem for path in trial_paths]

    episode_rows: list[dict] = []
    transition_rows: list[dict] = []
    sequence_rows: list[dict] = []
    all_true_seconds = np.zeros(4, dtype=np.float64)
    all_pred_seconds = np.zeros(4, dtype=np.float64)
    confusion_seconds = np.zeros((4, 4), dtype=np.float64)

    for participant in PARTICIPANTS:
        held_out_trials = [slug for slug in trial_slugs if slug.startswith(f"{participant}_")]
        model_path = MODEL_ROOT / f"held_out_{participant}" / "causal_lstm.npz"
        model = load_model(model_path)
        sequences, _, _ = load_raw_sequences(DATA_ROOT, held_out_trials)

        for sequence in sequences:
            labels = np.asarray(sequence.labels, dtype=np.int8)
            stamps = np.asarray(sequence.stamps_ns, dtype=np.int64)
            prediction, probability = fast_predict(model, sequence.features)
            dt, median_dt = durations_per_frame(stamps)
            duration_s = float(np.sum(dt))

            for true_phase in range(4):
                all_true_seconds[true_phase] += float(np.sum(dt[labels == true_phase]))
                all_pred_seconds[true_phase] += float(np.sum(dt[prediction == true_phase]))
                for predicted_phase in range(4):
                    confusion_seconds[true_phase, predicted_phase] += float(
                        np.sum(dt[(labels == true_phase) & (prediction == predicted_phase)])
                    )

            true_transitions = int(np.sum(labels[1:] != labels[:-1]))
            predicted_transitions = int(np.sum(prediction[1:] != prediction[:-1]))
            true_assist = labels == 2
            predicted_assist = prediction == 2
            true_assist_toggles = int(np.sum(true_assist[1:] != true_assist[:-1]))
            assist_toggles = int(np.sum(predicted_assist[1:] != predicted_assist[:-1]))
            predicted_runs = runs(prediction)
            short_150 = sum(
                elapsed(stamps, start, stop, median_dt) < 0.15
                for start, stop, _ in predicted_runs
            )
            short_300 = sum(
                elapsed(stamps, start, stop, median_dt) < 0.30
                for start, stop, _ in predicted_runs
            )

            sequence_rows.append(
                {
                    "participant": participant,
                    "trial": sequence.trial_slug,
                    "segment_id": sequence.segment_id,
                    "duration_s": duration_s,
                    "median_sample_rate_hz": 1.0 / median_dt,
                    "true_transitions": true_transitions,
                    "predicted_transitions": predicted_transitions,
                    "true_transitions_per_min": true_transitions / duration_s * 60.0,
                    "predicted_transitions_per_min": predicted_transitions / duration_s * 60.0,
                    "painting_assist_toggles": assist_toggles,
                    "true_painting_gate_toggles": true_assist_toggles,
                    "painting_assist_toggles_per_min": assist_toggles / duration_s * 60.0,
                    "predicted_runs": len(predicted_runs),
                    "predicted_runs_under_150ms": short_150,
                    "predicted_runs_under_300ms": short_300,
                    "missed_assist_s": float(np.sum(dt[true_assist & ~predicted_assist])),
                    "false_assist_s": float(np.sum(dt[~true_assist & predicted_assist])),
                    "painting_true_s": float(np.sum(dt[true_assist])),
                    "painting_predicted_s": float(np.sum(dt[predicted_assist])),
                }
            )

            label_runs = runs(labels)
            for episode_index, (start, stop, phase) in enumerate(label_runs):
                episode_duration = elapsed(stamps, start, stop, median_dt)
                within_prediction = prediction[start:stop]
                phase_mask = within_prediction == phase
                phase_predicted_runs = [
                    elapsed(stamps, start + a, start + b, median_dt)
                    for a, b, value in runs(within_prediction)
                    if value == phase
                ]
                longest_correct = max(phase_predicted_runs, default=0.0)
                any_detected = bool(np.any(phase_mask))
                stable_detected = longest_correct >= STABLE_SECONDS
                stable_delay = first_stable_target_delay(
                    prediction,
                    stamps,
                    start,
                    stop,
                    phase,
                    median_dt,
                    STABLE_SECONDS,
                )
                row = {
                    "participant": participant,
                    "trial": sequence.trial_slug,
                    "segment_id": sequence.segment_id,
                    "episode_index": episode_index,
                    "phase_id": phase,
                    "phase": str(PHASE_NAMES[phase]),
                    "start_time_s": float((stamps[start] - stamps[0]) / 1e9),
                    "duration_s": episode_duration,
                    "frames": stop - start,
                    "any_correct_prediction": int(any_detected),
                    "stable_150ms_correct_prediction": int(stable_detected),
                    "occupancy_recall": float(np.sum(dt[start:stop][phase_mask]) / np.sum(dt[start:stop])),
                    "longest_correct_run_s": longest_correct,
                    "delay_to_first_stable_150ms_s": stable_delay,
                }
                if phase == 2:
                    predicted_assist = prediction == 2
                    missed = float(np.sum(dt[start:stop][~predicted_assist[start:stop]]))
                    raw_delay = 0.0
                    if not predicted_assist[start]:
                        hits = np.flatnonzero(predicted_assist[start:stop])
                        raw_delay = (
                            float((stamps[start + int(hits[0])] - stamps[start]) / 1e9)
                            if len(hits)
                            else None
                        )
                    premature = continuous_duration_before(predicted_assist, stamps, start, median_dt)
                    release_linger = (
                        continuous_duration_after(predicted_assist, stamps, stop, median_dt)
                        if stop < len(labels)
                        else None
                    )
                    dropout_before_end = continuous_duration_before(
                        ~predicted_assist, stamps, stop, median_dt
                    )
                    row.update(
                        {
                            "missed_assist_s": missed,
                            "missed_assist_ratio": missed / episode_duration,
                            "raw_activation_delay_s": raw_delay,
                            "premature_assist_before_start_s": premature,
                            "release_linger_after_end_s": release_linger,
                            "assist_dropout_before_end_s": dropout_before_end,
                            "assist_toggles_inside_episode": int(
                                np.sum(
                                    predicted_assist[start + 1 : stop]
                                    != predicted_assist[start : stop - 1]
                                )
                            ),
                        }
                    )
                else:
                    row.update(
                        {
                            "missed_assist_s": None,
                            "missed_assist_ratio": None,
                            "raw_activation_delay_s": None,
                            "premature_assist_before_start_s": None,
                            "release_linger_after_end_s": None,
                            "assist_dropout_before_end_s": None,
                            "assist_toggles_inside_episode": None,
                        }
                    )
                episode_rows.append(row)

            for boundary_number, boundary in enumerate(np.flatnonzero(labels[1:] != labels[:-1]) + 1):
                boundary = int(boundary)
                previous_phase = int(labels[boundary - 1])
                target_phase = int(labels[boundary])
                target_stop = boundary + 1
                while target_stop < len(labels) and labels[target_stop] == target_phase:
                    target_stop += 1
                previous_start = boundary - 1
                while previous_start > 0 and labels[previous_start - 1] == previous_phase:
                    previous_start -= 1

                any_hits = np.flatnonzero(prediction[boundary:target_stop] == target_phase)
                any_delay = (
                    float((stamps[boundary + int(any_hits[0])] - stamps[boundary]) / 1e9)
                    if len(any_hits)
                    else None
                )
                stable_delay = first_stable_target_delay(
                    prediction,
                    stamps,
                    boundary,
                    target_stop,
                    target_phase,
                    median_dt,
                    STABLE_SECONDS,
                )
                previous_linger = continuous_duration_after(
                    prediction == previous_phase, stamps, boundary, median_dt
                )
                local_start = int(np.searchsorted(stamps, int(stamps[boundary] - 1e9), side="left"))
                local_stop = int(np.searchsorted(stamps, int(stamps[boundary] + 1e9), side="right"))

                transition_row = {
                    "participant": participant,
                    "trial": sequence.trial_slug,
                    "segment_id": sequence.segment_id,
                    "boundary_number": boundary_number,
                    "from_phase_id": previous_phase,
                    "from_phase": str(PHASE_NAMES[previous_phase]),
                    "to_phase_id": target_phase,
                    "to_phase": str(PHASE_NAMES[target_phase]),
                    "transition": f"{PHASE_NAMES[previous_phase]}->{PHASE_NAMES[target_phase]}",
                    "boundary_time_s": float((stamps[boundary] - stamps[0]) / 1e9),
                    "previous_phase_duration_s": elapsed(
                        stamps, previous_start, boundary, median_dt
                    ),
                    "target_phase_duration_s": elapsed(stamps, boundary, target_stop, median_dt),
                    "predicted_phase_at_boundary": str(PHASE_NAMES[int(prediction[boundary])]),
                    "target_correct_at_boundary": int(prediction[boundary] == target_phase),
                    "target_probability_at_boundary": float(probability[boundary, target_phase]),
                    "previous_probability_at_boundary": float(probability[boundary, previous_phase]),
                    "delay_to_any_target_s": any_delay,
                    "delay_to_stable_150ms_target_s": stable_delay,
                    "previous_phase_linger_s": previous_linger,
                    "predicted_switches_within_1s_each_side": int(
                        np.sum(prediction[local_start + 1 : local_stop] != prediction[local_start : local_stop - 1])
                    ),
                }
                for offset in PROFILE_OFFSETS_S:
                    target_ns = int(stamps[boundary] + offset * 1e9)
                    index = nearest_index(stamps, target_ns)
                    key = f"target_probability_{offset:+.2f}s"
                    transition_row[key] = (
                        float(probability[index, target_phase])
                        if index is not None and abs(int(stamps[index]) - target_ns) <= 0.08e9
                        else None
                    )
                transition_rows.append(transition_row)

    write_csv(OUTPUT_ROOT / "phase_episodes.csv", episode_rows)
    write_csv(OUTPUT_ROOT / "transition_events.csv", transition_rows)
    write_csv(OUTPUT_ROOT / "sequence_control_summary.csv", sequence_rows)

    episode_summary = {}
    for phase_id, phase_name in enumerate(PHASE_NAMES):
        selected = [row for row in episode_rows if row["phase_id"] == phase_id]
        durations = [row["duration_s"] for row in selected]
        episode_summary[str(phase_name)] = {
            "episodes": len(selected),
            "duration_s": stats(durations),
            "duration_under_0.25s_percent": 100.0 * np.mean([v < 0.25 for v in durations]),
            "duration_under_0.50s_percent": 100.0 * np.mean([v < 0.50 for v in durations]),
            "duration_under_1.00s_percent": 100.0 * np.mean([v < 1.00 for v in durations]),
            "any_detection_percent": 100.0 * np.mean([row["any_correct_prediction"] for row in selected]),
            "stable_150ms_detection_percent": 100.0
            * np.mean([row["stable_150ms_correct_prediction"] for row in selected]),
            "occupancy_recall": stats([row["occupancy_recall"] for row in selected]),
            "delay_to_first_stable_150ms_s": stats(
                [row["delay_to_first_stable_150ms_s"] for row in selected]
            ),
        }

    transition_summary = {}
    transition_types = sorted(set(row["transition"] for row in transition_rows))
    for transition_type in transition_types:
        selected = [row for row in transition_rows if row["transition"] == transition_type]
        profile = {}
        for offset in PROFILE_OFFSETS_S:
            key = f"target_probability_{offset:+.2f}s"
            profile[f"{offset:+.2f}"] = stats([row[key] for row in selected])
        transition_summary[transition_type] = {
            "events": len(selected),
            "target_correct_at_boundary_percent": 100.0
            * np.mean([row["target_correct_at_boundary"] for row in selected]),
            "target_probability_at_boundary": stats(
                [row["target_probability_at_boundary"] for row in selected]
            ),
            "delay_to_any_target_s": stats([row["delay_to_any_target_s"] for row in selected]),
            "delay_to_stable_150ms_target_s": stats(
                [row["delay_to_stable_150ms_target_s"] for row in selected]
            ),
            "stable_detection_within_target_episode_percent": 100.0
            * np.mean([row["delay_to_stable_150ms_target_s"] is not None for row in selected]),
            "previous_phase_linger_s": stats([row["previous_phase_linger_s"] for row in selected]),
            "predicted_switches_within_1s_each_side": stats(
                [row["predicted_switches_within_1s_each_side"] for row in selected]
            ),
            "target_probability_profile": profile,
        }

    short_phase_detection = {}
    duration_bins = (
        ("under_0.5s", 0.0, 0.5),
        ("0.5_to_1.0s", 0.5, 1.0),
        ("1.0_to_2.0s", 1.0, 2.0),
        ("2.0s_or_more", 2.0, float("inf")),
    )
    for phase_id in (1, 3):
        phase_name = str(PHASE_NAMES[phase_id])
        phase_rows = [row for row in episode_rows if row["phase_id"] == phase_id]
        short_phase_detection[phase_name] = {}
        for bin_name, lower, upper in duration_bins:
            selected = [row for row in phase_rows if lower <= row["duration_s"] < upper]
            short_phase_detection[phase_name][bin_name] = {
                "episodes": len(selected),
                "any_detection_percent": 100.0
                * np.mean([row["any_correct_prediction"] for row in selected])
                if selected
                else None,
                "stable_150ms_detection_percent": 100.0
                * np.mean([row["stable_150ms_correct_prediction"] for row in selected])
                if selected
                else None,
                "occupancy_recall": stats([row["occupancy_recall"] for row in selected]),
            }

    painting_episodes = [row for row in episode_rows if row["phase_id"] == 2]
    painting_entry_counts = Counter(
        row["from_phase"] for row in transition_rows if row["to_phase_id"] == 2
    )
    painting_exit_counts = Counter(
        row["to_phase"] for row in transition_rows if row["from_phase_id"] == 2
    )
    painting_starts_at_sequence_start = sum(
        1
        for row in episode_rows
        if row["phase_id"] == 2 and abs(row["start_time_s"]) < 1e-9
    )
    painting_ends_at_sequence_end = len(painting_episodes) - sum(painting_exit_counts.values())

    total_duration = sum(row["duration_s"] for row in sequence_rows)
    total_true_transitions = sum(row["true_transitions"] for row in sequence_rows)
    total_pred_transitions = sum(row["predicted_transitions"] for row in sequence_rows)
    total_assist_toggles = sum(row["painting_assist_toggles"] for row in sequence_rows)
    total_true_assist_toggles = sum(row["true_painting_gate_toggles"] for row in sequence_rows)
    total_missed_assist = sum(row["missed_assist_s"] for row in sequence_rows)
    total_false_assist = sum(row["false_assist_s"] for row in sequence_rows)
    total_painting_true = sum(row["painting_true_s"] for row in sequence_rows)
    total_nonpainting_true = total_duration - total_painting_true
    participant_rows = []
    for participant in PARTICIPANTS:
        participant_sequences = [row for row in sequence_rows if row["participant"] == participant]
        participant_episodes = [row for row in episode_rows if row["participant"] == participant]
        participant_painting = [row for row in participant_episodes if row["phase_id"] == 2]
        participant_approach = [row for row in participant_episodes if row["phase_id"] == 1]
        participant_retract = [row for row in participant_episodes if row["phase_id"] == 3]
        participant_duration = sum(row["duration_s"] for row in participant_sequences)
        participant_painting_s = sum(row["painting_true_s"] for row in participant_sequences)
        participant_nonpainting_s = participant_duration - participant_painting_s
        participant_rows.append(
            {
                "participant": participant,
                "trials": len(set(row["trial"] for row in participant_sequences)),
                "duration_min": participant_duration / 60.0,
                "predicted_phase_switches_per_min": sum(
                    row["predicted_transitions"] for row in participant_sequences
                )
                / participant_duration
                * 60.0,
                "painting_gate_toggles_per_min": sum(
                    row["painting_assist_toggles"] for row in participant_sequences
                )
                / participant_duration
                * 60.0,
                "missed_painting_gate_percent": 100.0
                * sum(row["missed_assist_s"] for row in participant_sequences)
                / participant_painting_s,
                "false_painting_gate_percent_of_nonpainting": 100.0
                * sum(row["false_assist_s"] for row in participant_sequences)
                / participant_nonpainting_s,
                "approach_stable_detection_percent": 100.0
                * np.mean([row["stable_150ms_correct_prediction"] for row in participant_approach])
                if participant_approach
                else None,
                "retract_stable_detection_percent": 100.0
                * np.mean([row["stable_150ms_correct_prediction"] for row in participant_retract])
                if participant_retract
                else None,
                "painting_release_linger_median_s": stats(
                    [row["release_linger_after_end_s"] for row in participant_painting]
                )["median"],
            }
        )
    write_csv(OUTPUT_ROOT / "participant_control_summary.csv", participant_rows)

    false_assist_by_true_phase = {}
    for phase_id, phase_name in enumerate(PHASE_NAMES):
        if phase_id == 2:
            continue
        false_s = float(confusion_seconds[phase_id, 2])
        false_assist_by_true_phase[str(phase_name)] = {
            "seconds": false_s,
            "percent_of_true_phase_time": 100.0 * false_s / all_true_seconds[phase_id],
            "percent_of_all_false_assist_time": 100.0 * false_s / total_false_assist
            if total_false_assist
            else 0.0,
        }

    summary = {
        "analysis": {
            "model": "Causal LSTM",
            "evaluation": "six-fold leave-one-participant-out",
            "checkpoint_scope": (
                "one saved Causal LSTM checkpoint per held-out participant; the stored five-seed "
                "summary does not include framewise outputs for repeating this analysis across seeds"
            ),
            "participants": list(PARTICIPANTS),
            "trials": len(set(row["trial"] for row in sequence_rows)),
            "valid_sequences": len(sequence_rows),
            "total_duration_s": total_duration,
            "stable_detection_definition_s": STABLE_SECONDS,
            "important_note": (
                "This is offline replay of causal predictions. It estimates switching-signal "
                "quality but does not measure robot contact force or human-robot conflict."
            ),
        },
        "phase_episode_summary": episode_summary,
        "short_phase_detection_by_duration": short_phase_detection,
        "painting_boundary_label_structure": {
            "painting_episodes": len(painting_episodes),
            "entry_from_phase_counts": dict(painting_entry_counts),
            "starts_at_sequence_start": painting_starts_at_sequence_start,
            "exit_to_phase_counts": dict(painting_exit_counts),
            "ends_at_sequence_end": painting_ends_at_sequence_end,
            "approach_precedes_percent_of_all_painting_episodes": 100.0
            * painting_entry_counts["APPROACH"]
            / len(painting_episodes),
            "retract_follows_percent_of_all_painting_episodes": 100.0
            * painting_exit_counts["RETRACT"]
            / len(painting_episodes),
        },
        "transition_summary": transition_summary,
        "direct_painting_assistance_mapping": {
            "definition": "phase gate open iff raw argmax prediction is PAINTING",
            "button_caveat": (
                "Actual assistance also requires the A/B request. The recorded data contain no "
                "future A/B policy, so these values measure phase-gate exposure, not actual robot assistance."
            ),
            "true_transition_rate_per_min": total_true_transitions / total_duration * 60.0,
            "predicted_phase_switch_rate_per_min": total_pred_transitions / total_duration * 60.0,
            "predicted_to_true_transition_count_ratio": total_pred_transitions
            / total_true_transitions,
            "painting_assistance_toggle_rate_per_min": total_assist_toggles / total_duration * 60.0,
            "true_painting_gate_toggle_rate_per_min": total_true_assist_toggles
            / total_duration
            * 60.0,
            "predicted_to_true_painting_gate_toggle_ratio": total_assist_toggles
            / total_true_assist_toggles,
            "missed_assistance_seconds": total_missed_assist,
            "missed_assistance_percent_of_true_painting": 100.0
            * total_missed_assist
            / total_painting_true,
            "false_assistance_seconds": total_false_assist,
            "false_assistance_percent_of_nonpainting": 100.0
            * total_false_assist
            / total_nonpainting_true,
            "false_assistance_by_true_phase": false_assist_by_true_phase,
            "painting_episode_raw_activation_delay_s": stats(
                [row["raw_activation_delay_s"] for row in painting_episodes]
            ),
            "painting_episode_stable_activation_delay_s": stats(
                [row["delay_to_first_stable_150ms_s"] for row in painting_episodes]
            ),
            "painting_episode_release_linger_s": stats(
                [row["release_linger_after_end_s"] for row in painting_episodes]
            ),
            "painting_episode_assist_dropout_before_end_s": stats(
                [row["assist_dropout_before_end_s"] for row in painting_episodes]
            ),
            "painting_episode_internal_toggle_count": stats(
                [row["assist_toggles_inside_episode"] for row in painting_episodes]
            ),
            "participant_summary": participant_rows,
        },
        "time_weighted_confusion_seconds": confusion_seconds.tolist(),
        "time_weighted_confusion_row_percent": (
            confusion_seconds / np.maximum(confusion_seconds.sum(axis=1, keepdims=True), 1e-12) * 100.0
        ).tolist(),
    }

    with (OUTPUT_ROOT / "transition_aware_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False, default=scalar)

    canonical = [
        "FREE_MOTION->APPROACH",
        "APPROACH->PAINTING",
        "PAINTING->RETRACT",
        "RETRACT->FREE_MOTION",
    ]
    lines = [
        "# Transition-aware analysis of the LOPO Causal LSTM",
        "",
        f"- Data: {summary['analysis']['trials']} trials, {summary['analysis']['valid_sequences']} valid sequences, "
        f"{total_duration / 60.0:.1f} min",
        f"- Stable detection: the predicted target phase persists for at least {STABLE_SECONDS * 1000:.0f} ms",
        "- This is causal offline replay; no robot controller or contact-force outcome is included.",
        "- One saved checkpoint per LOPO fold was available; this is not a five-seed transition analysis.",
        "",
        "## Phase episode duration and detectability",
        "",
        "| Phase | Episodes | Median duration (s) | <0.5 s | Any detection | Stable 150-ms detection | Median occupancy recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for phase_name in PHASE_NAMES:
        value = episode_summary[str(phase_name)]
        lines.append(
            f"| {phase_name} | {value['episodes']} | {value['duration_s']['median']:.3f} | "
            f"{value['duration_under_0.50s_percent']:.1f}% | {value['any_detection_percent']:.1f}% | "
            f"{value['stable_150ms_detection_percent']:.1f}% | {value['occupancy_recall']['median']:.3f} |"
        )
    lines.extend(
        [
            "",
            "### Short transition-phase detectability",
            "",
            "| Phase | Episode duration | N | Any detection | Stable 150-ms detection | Median occupancy recall |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for phase_name in ("APPROACH", "RETRACT"):
        for bin_name, value in short_phase_detection[phase_name].items():
            lines.append(
                f"| {phase_name} | {bin_name} | {value['episodes']} | "
                f"{value['any_detection_percent']:.1f}% | "
                f"{value['stable_150ms_detection_percent']:.1f}% | "
                f"{value['occupancy_recall']['median']:.3f} |"
            )
    boundary = {
        "approach": 100.0 * painting_entry_counts["APPROACH"] / len(painting_episodes),
        "retract": 100.0 * painting_exit_counts["RETRACT"] / len(painting_episodes),
    }
    lines.extend(
        [
            "",
            "### Label-chain coverage",
            "",
            f"- {painting_entry_counts['APPROACH']} of {len(painting_episodes)} Painting episodes "
            f"({boundary['approach']:.1f}%) were preceded by an explicit Approach label.",
            f"- {painting_exit_counts['RETRACT']} of {len(painting_episodes)} Painting episodes "
            f"({boundary['retract']:.1f}%) were followed by an explicit Retract label.",
            "- Therefore, FREE-APPROACH-PAINTING-RETRACT-FREE is not a mandatory label chain in the current data.",
        ]
    )
    lines.extend(
        [
            "",
            "## Canonical transition behavior",
            "",
            "| Transition | N | Correct exactly at boundary | Stable detection in target episode | Median stable delay (s) | Median switches in +/-1 s |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for name in canonical:
        if name not in transition_summary:
            continue
        value = transition_summary[name]
        delay = value["delay_to_stable_150ms_target_s"]["median"]
        delay_text = "NA" if delay is None else f"{delay:.3f}"
        lines.append(
            f"| {name} | {value['events']} | {value['target_correct_at_boundary_percent']:.1f}% | "
            f"{value['stable_detection_within_target_episode_percent']:.1f}% | {delay_text} | "
            f"{value['predicted_switches_within_1s_each_side']['median']:.1f} |"
        )
    direct = summary["direct_painting_assistance_mapping"]
    lines.extend(
        [
            "",
            "## Direct PAINTING-to-assistance mapping",
            "",
            f"- True phase transitions: {direct['true_transition_rate_per_min']:.2f}/min",
            f"- Predicted phase switches: {direct['predicted_phase_switch_rate_per_min']:.2f}/min "
            f"({direct['predicted_to_true_transition_count_ratio']:.2f}x the true count)",
            f"- Painting phase-gate toggles: {direct['painting_assistance_toggle_rate_per_min']:.2f}/min",
            f"- True Painting gate toggles: {direct['true_painting_gate_toggle_rate_per_min']:.2f}/min "
            f"(prediction: {direct['predicted_to_true_painting_gate_toggle_ratio']:.2f}x)",
            f"- Closed phase gate during true Painting: {direct['missed_assistance_percent_of_true_painting']:.1f}%",
            f"- Open phase gate outside true Painting: {direct['false_assistance_percent_of_nonpainting']:.1f}%",
            "- Actual assistance still depends on A/B; these are phase-gate errors, not measured robot actions.",
            "",
            "### Open Painting phase gate by true phase",
            "",
        ]
    )
    for phase_name, value in direct["false_assistance_by_true_phase"].items():
        lines.append(
            f"- {phase_name}: {value['seconds']:.1f} s "
            f"({value['percent_of_true_phase_time']:.1f}% of that phase; "
            f"{value['percent_of_all_false_assist_time']:.1f}% of false-assist time)"
        )
    (OUTPUT_ROOT / "TRANSITION_AWARE_ANALYSIS.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False, default=scalar))


if __name__ == "__main__":
    main()
