"""Common model loading for command-line tools."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .discriminative import (
    CausalLSTMPhaseModel,
    DISCRIMINATIVE_MODEL_TYPES,
    RandomForestPhaseModel,
    load_discriminative_model,
)
from .fsm import CausalFSMModel, load_causal_fsm
from .probabilistic import PhaseModel, load_phase_model


AnyPhaseModel = CausalFSMModel | PhaseModel | RandomForestPhaseModel | CausalLSTMPhaseModel


def read_model_type(path: Path) -> str:
    with np.load(path) as values:
        return str(values["model_type"])


def load_model(path: Path) -> AnyPhaseModel:
    model_type = read_model_type(path)
    if model_type == "causal_fsm":
        return load_causal_fsm(path)
    if model_type in DISCRIMINATIVE_MODEL_TYPES:
        return load_discriminative_model(path)
    return load_phase_model(path)
