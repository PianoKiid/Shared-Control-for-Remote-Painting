"""Metrics shared by training diagnostics and held-out evaluation."""

from __future__ import annotations

import numpy as np


def confusion_matrix(labels: np.ndarray, predictions: np.ndarray, classes: int = 4) -> np.ndarray:
    truth = np.asarray(labels, dtype=np.int64)
    estimated = np.asarray(predictions, dtype=np.int64)
    if truth.shape != estimated.shape:
        raise ValueError("labels and predictions must have the same shape")
    matrix = np.zeros((classes, classes), dtype=np.int64)
    np.add.at(matrix, (truth, estimated), 1)
    return matrix


def classification_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict[str, object]:
    matrix = confusion_matrix(labels, predictions)
    total = int(matrix.sum())
    recalls: list[float] = []
    f1_scores: list[float] = []
    for phase in range(4):
        true_positive = float(matrix[phase, phase])
        false_negative = float(matrix[phase].sum() - matrix[phase, phase])
        false_positive = float(matrix[:, phase].sum() - matrix[phase, phase])
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        recalls.append(recall)
        f1_scores.append(f1)
    return {
        "samples": total,
        "accuracy": float(np.trace(matrix) / total) if total else 0.0,
        "balanced_accuracy": float(np.mean(recalls)),
        "macro_f1": float(np.mean(f1_scores)),
        "phase_recall": recalls,
        "phase_f1": f1_scores,
        "confusion_matrix_rows_true_columns_predicted": matrix.tolist(),
    }
