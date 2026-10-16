import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".analysis_deps"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from phase_modeling.data import available_trials, load_raw_sequences, load_training_data
from phase_modeling.discriminative import fit_random_forest
from phase_modeling.fsm import fit_causal_fsm
from phase_modeling.metrics import classification_metrics
from phase_modeling.model_io import load_model
from phase_modeling.probabilistic import PhaseModel, fit_probabilistic_model, transition_parameters


DATA_ROOT = ROOT / "data" / "processed" / "phase_model_inputs_v1"
RESULT_ROOT = ROOT / "results" / "phase_learning" / "final_lopo" / "results" / "tolerant_3s"
FIGURE_PATH = RESULT_ROOT / "lopo_08_01_phase_timeline.png"
PREDICTION_PATH = RESULT_ROOT / "lopo_08_01_phase_predictions.npz"
METADATA_PATH = RESULT_ROOT / "lopo_08_01_phase_timeline_metadata.json"
LSTM_PATH = (
    ROOT
    / "results"
    / "phase_learning"
    / "final_lopo"
    / "models"
    / "causal_lstm_all_folds"
    / "held_out_08"
    / "causal_lstm.npz"
)

FONT_REGULAR = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\arialbd.ttf")

MODEL_ORDER = [
    ("causal_fsm", "Causal FSM"),
    ("random_forest", "Random Forest"),
    ("gmm", "GMM"),
    ("gaussian_hmm", "Gaussian HMM"),
    ("gmm_hmm", "GMM–HMM"),
    ("causal_lstm", "Causal LSTM"),
]

PHASE_COLORS = {
    0: "#587EA3",  # Free Motion
    1: "#D69A4B",  # Approach
    2: "#A8D08D",  # Painting
    3: "#B8646B",  # Retract
}
PHASE_LABELS = ["Free Motion", "Approach", "Painting", "Retract"]


def font(size, bold=False):
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size=size)


def predict_sequences(model, sequences):
    outputs = []
    probabilities = []
    for sequence in sequences:
        prediction, probability = model.predict_sequence(sequence.features)
        outputs.append(np.asarray(prediction, dtype=np.int8))
        probabilities.append(np.asarray(probability, dtype=np.float32))
    return outputs, probabilities


def run_intervals(stamps_ns, labels):
    labels = np.asarray(labels, dtype=np.int8)
    stamps_ns = np.asarray(stamps_ns, dtype=np.int64)
    if len(labels) == 0:
        return []
    boundaries = np.r_[0, np.flatnonzero(labels[1:] != labels[:-1]) + 1, len(labels)]
    dt = int(np.median(np.diff(stamps_ns))) if len(stamps_ns) > 1 else 33_333_333
    result = []
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        start_ns = int(stamps_ns[start])
        stop_ns = int(stamps_ns[stop]) if stop < len(stamps_ns) else int(stamps_ns[-1] + dt)
        result.append((start_ns, stop_ns, int(labels[start])))
    return result


def create_figure(sequences, predictions_by_model):
    width, height = 3600, 1450
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = font(60, bold=True)
    subtitle_font = font(32)
    legend_font = font(31)
    row_font = font(35)
    row_bold_font = font(35, bold=True)
    tick_font = font(28)
    segment_font = font(25)

    draw.text((width / 2, 62), "LOPO Phase Recognition — Trial 08_01", font=title_font, fill="#202020", anchor="ma")
    draw.text(
        (width / 2, 137),
        "Participant 08 held out from training",
        font=subtitle_font,
        fill="#555555",
        anchor="ma",
    )

    legend_y = 228
    item_widths = []
    for label in PHASE_LABELS:
        bbox = draw.textbbox((0, 0), label, font=legend_font)
        item_widths.append(48 + 16 + bbox[2] - bbox[0] + 62)
    cursor = (width - sum(item_widths)) / 2
    for phase, (label, item_width) in enumerate(zip(PHASE_LABELS, item_widths)):
        draw.rectangle((cursor, legend_y - 18, cursor + 48, legend_y + 20), fill=PHASE_COLORS[phase])
        draw.text((cursor + 64, legend_y + 1), label, font=legend_font, fill="#303030", anchor="lm")
        cursor += item_width

    plot_left, plot_right = 515, width - 130
    plot_top = 350
    row_height, row_gap = 92, 34
    plot_bottom = plot_top + 7 * row_height + 6 * row_gap
    start_ns = min(int(sequence.stamps_ns[0]) for sequence in sequences)
    end_ns = max(int(sequence.stamps_ns[-1]) for sequence in sequences)
    total_seconds = (end_ns - start_ns) / 1e9

    def x_px(stamp_ns):
        fraction = (int(stamp_ns) - start_ns) / max(end_ns - start_ns, 1)
        return plot_left + fraction * (plot_right - plot_left)

    # Light gray indicates time gaps between valid contiguous segments.
    for row_index in range(7):
        y0 = plot_top + row_index * (row_height + row_gap)
        draw.rounded_rectangle(
            (plot_left, y0, plot_right, y0 + row_height),
            radius=8,
            fill="#ECEFF2",
            outline="#C9CED4",
            width=2,
        )

    row_items = [("Ground Truth", [sequence.labels for sequence in sequences])]
    for model_key, model_label in MODEL_ORDER:
        row_items.append((model_label, predictions_by_model[model_key]))

    for row_index, (row_label, sequence_labels) in enumerate(row_items):
        y0 = plot_top + row_index * (row_height + row_gap)
        y1 = y0 + row_height
        draw.text(
            (plot_left - 34, (y0 + y1) / 2),
            row_label,
            font=row_bold_font if row_index == 0 else row_font,
            fill="#202020",
            anchor="rm",
        )
        for sequence, labels in zip(sequences, sequence_labels):
            for interval_start, interval_stop, phase in run_intervals(sequence.stamps_ns, labels):
                x0 = x_px(interval_start)
                x1 = max(x0 + 1, x_px(interval_stop))
                draw.rectangle((x0, y0 + 2, x1, y1 - 2), fill=PHASE_COLORS[phase])
        draw.rounded_rectangle(
            (plot_left, y0, plot_right, y1),
            radius=8,
            outline="#AEB4BA",
            width=2,
        )

    # Mark valid segment centers and boundaries above the bands.
    for idx, sequence in enumerate(sequences, start=1):
        x0 = x_px(sequence.stamps_ns[0])
        x1 = x_px(sequence.stamps_ns[-1])
        draw.text(
            ((x0 + x1) / 2, plot_top - 24),
            f"Segment {idx}",
            font=segment_font,
            fill="#666666",
            anchor="ms",
        )

    axis_y = plot_bottom + 50
    draw.line((plot_left, axis_y, plot_right, axis_y), fill="#333333", width=4)
    max_minute = int(total_seconds // 60)
    for minute in range(max_minute + 1):
        stamp = start_ns + int(minute * 60 * 1e9)
        x = x_px(stamp)
        draw.line((x, axis_y, x, axis_y + 16), fill="#333333", width=3)
        draw.text((x, axis_y + 28), str(minute), font=tick_font, fill="#333333", anchor="ma")
    draw.text(
        ((plot_left + plot_right) / 2, axis_y + 92),
        "Elapsed time (min)",
        font=row_font,
        fill="#222222",
        anchor="ma",
    )
    draw.text(
        (plot_right, axis_y + 92),
        "Gray intervals indicate gaps between valid segments.",
        font=segment_font,
        fill="#666666",
        anchor="ra",
    )

    image.save(FIGURE_PATH, dpi=(300, 300), optimize=True)


all_trials = available_trials(DATA_ROOT)
train_trials = [trial for trial in all_trials if not trial.startswith("08_")]
test_trials = [trial for trial in all_trials if trial.startswith("08_")]
print(f"Training on {len(train_trials)} trials; held out: {test_trials}", flush=True)

training_data = load_training_data(DATA_ROOT, train_trials)

models = {}
print("Fitting Causal FSM", flush=True)
models["causal_fsm"] = fit_causal_fsm(training_data)

print("Fitting Random Forest", flush=True)
models["random_forest"] = fit_random_forest(training_data, seed=0)

print("Fitting GMM", flush=True)
gmm_model = fit_probabilistic_model("gmm", training_data, components=3, seed=0)
models["gmm"] = gmm_model

print("Fitting Gaussian HMM", flush=True)
models["gaussian_hmm"] = fit_probabilistic_model(
    "gaussian_hmm", training_data, components=1, seed=0
)

print("Constructing GMM-HMM from the identical fitted emissions", flush=True)
initial, transition = transition_parameters(training_data.sequences, 0.1, allow_self=True)
models["gmm_hmm"] = PhaseModel(
    model_type="gmm_hmm",
    scaler_mean=training_data.scaler_mean,
    scaler_scale=training_data.scaler_scale,
    class_prior=initial,
    transition=transition,
    mixture_weights=gmm_model.mixture_weights.copy(),
    mixture_means=gmm_model.mixture_means.copy(),
    mixture_variances=gmm_model.mixture_variances.copy(),
    feature_names=training_data.feature_names,
    label_version=training_data.label_version,
    metadata={"source": "same held-out-08 GMM emissions; causal forward filtering"},
)

print("Loading saved held-out-08 Causal LSTM", flush=True)
models["causal_lstm"] = load_model(LSTM_PATH)

trial_sequences, _, _ = load_raw_sequences(DATA_ROOT, ["08_01"])
predictions_by_model = {}
probabilities_by_model = {}
for model_key, _ in MODEL_ORDER:
    predictions, probabilities = predict_sequences(models[model_key], trial_sequences)
    predictions_by_model[model_key] = predictions
    probabilities_by_model[model_key] = probabilities

create_figure(trial_sequences, predictions_by_model)

save_values = {
    "sequence_lengths": np.asarray([len(sequence.labels) for sequence in trial_sequences], dtype=np.int64),
    "stamps_ns": np.concatenate([sequence.stamps_ns for sequence in trial_sequences]),
    "ground_truth": np.concatenate([sequence.labels for sequence in trial_sequences]),
}
for model_key, _ in MODEL_ORDER:
    save_values[f"{model_key}_prediction"] = np.concatenate(predictions_by_model[model_key])
    save_values[f"{model_key}_probability"] = np.concatenate(probabilities_by_model[model_key])
np.savez_compressed(PREDICTION_PATH, **save_values)

# Validate the reproduced held-out fold against all participant-08 trials.
fold_metrics = {}
all_test_sequences, _, _ = load_raw_sequences(DATA_ROOT, test_trials)
true_all = np.concatenate([sequence.labels for sequence in all_test_sequences])
for model_key, model_label in MODEL_ORDER:
    prediction_all, _ = predict_sequences(models[model_key], all_test_sequences)
    metrics = classification_metrics(true_all, np.concatenate(prediction_all))
    fold_metrics[model_key] = {
        "model": model_label,
        "strict_accuracy": float(metrics["accuracy"]),
        "strict_macro_f1": float(metrics["macro_f1"]),
    }

metadata = {
    "figure": FIGURE_PATH.name,
    "trial": "08_01",
    "held_out_participant": "08",
    "training_trials": train_trials,
    "test_trials_for_fold_validation": test_trials,
    "model_order": [key for key, _ in MODEL_ORDER],
    "phase_ids": {"0": "FREE_MOTION", "1": "APPROACH", "2": "PAINTING", "3": "RETRACT"},
    "strict_fold_metrics": fold_metrics,
    "note": "Predictions are causal. The ±3-s tolerance affects scoring only and does not alter these timelines.",
}
METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps(fold_metrics, indent=2), flush=True)
print(FIGURE_PATH, flush=True)
print(PREDICTION_PATH, flush=True)
print(METADATA_PATH, flush=True)
