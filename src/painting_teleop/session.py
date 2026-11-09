"""Trial recording and a shared live/replay control pipeline."""

import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from .controller import Controller, Observation, Parameters
from .features import CausalFeatureExtractor
from .lstm import PhaseLSTM
from .metrics import summarize

TASKS = ("FREE", "APPROACH", "PAINTING", "RETRACT")


class ControlSession:
    def __init__(
        self, config, root, condition="shared", phase_delay_frames=0, force_phase=None
    ):
        self.config = config
        self.condition = condition
        self.controller = Controller(Parameters(**config["controller"]), condition)
        self.model = PhaseLSTM(Path(root) / config["checkpoint"])
        self.features = CausalFeatureExtractor(force_offset_tcp_N=np.zeros(3))
        self.delay = int(phase_delay_frames)
        self.force_phase = force_phase
        self.history = []
        if self.delay < 0 or force_phase not in (None, *TASKS):
            raise ValueError("Invalid phase fault")

    def step(self, t, position, force_ft, human, normal_force, gap, enabled):
        dt = 1 / self.config["control_hz"]
        frame = self.features.step(force_ft, position, round(t * 1e9))
        if frame.reset:
            self.model.reset()
            self.history.clear()
            self.controller.reset()
        probability = np.array([1.0, 0.0, 0.0, 0.0])
        if frame.valid:
            probability = self.model.step(frame.features)
        self.history.append(probability.copy())
        used = self.history[max(0, len(self.history) - 1 - self.delay)]
        if len(self.history) > self.delay + 2:
            self.history.pop(0)
        if self.force_phase is not None:
            used = np.eye(4)[TASKS.index(self.force_phase)]
        human = np.asarray(human, float)
        if human.shape != (3,) or not np.isfinite(human).all():
            raise ValueError("Invalid operator velocity")
        human = np.clip(
            human,
            -self.config["max_translation_speed_m_s"],
            self.config["max_translation_speed_m_s"],
        )
        human[0] = np.clip(
            human[0],
            -self.controller.params.max_normal_speed_m_s,
            self.controller.params.max_normal_speed_m_s,
        )
        active = bool(enabled and frame.valid)
        decision = self.controller.step(
            Observation(dt, float(human[0]), normal_force, gap, used, active)
        )
        command = human.copy() if active else np.zeros(3)
        command[0] = decision.command
        return command, decision, probability, used, frame.valid, human


class TrialLogger:
    def __init__(self, directory, metadata):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = dict(metadata)
        self.rows = []
        self.writer = None
        self.closed = False
        self.file = (self.directory / "samples.csv").open(
            "w", newline="", encoding="utf-8"
        )
        (self.directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def write(self, row):
        if self.writer is None:
            self.writer = csv.DictWriter(self.file, fieldnames=list(row))
            self.writer.writeheader()
        self.writer.writerow(row)
        self.rows.append(row)
        if len(self.rows) % 30 == 0:
            self.file.flush()

    def close(self, status="completed"):
        if self.closed:
            return
        self.closed = True
        self.file.close()
        result = summarize(
            self.rows, self.metadata["config"]["controller"]["desired_force_N"]
        )
        result.update(status=status, condition=self.metadata["condition"])
        (self.directory / "summary.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )


def model_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sample_row(
    t,
    dt,
    wall_elapsed,
    task,
    force,
    gap,
    position,
    human,
    command,
    decision,
    prob,
    used,
    enabled,
    valid,
    tracking_error=0.0,
    fault="",
    input_raw=None,
):
    if task not in (*TASKS, "UNMARKED"):
        raise ValueError("Unknown independent task marker")
    row = dict(
        time_s=t,
        dt_s=dt,
        wall_elapsed_s=wall_elapsed,
        task=task,
        force_N=force,
        gap_m=gap,
        x_m=float(position[0]),
        y_m=float(position[1]),
        z_m=float(position[2]),
        human_normal_m_s=float(human[0]),
        command_normal_m_s=float(command[0]),
        authority=decision.authority,
        mode=decision.mode,
        contact=decision.contact,
        released=decision.released,
        enabled=enabled,
        feature_valid=valid,
        tracking_error_m=tracking_error,
        fault=fault,
    )
    for prefix, vec in [
        ("human", human),
        ("command", command),
        ("input_raw", human if input_raw is None else input_raw),
    ]:
        for axis, value in zip("xyz", vec):
            row[f"{prefix}_{axis}_m_s"] = float(value)
    for prefix, vec in [("p", prob), ("used_p", used)]:
        for label, value in zip(TASKS, vec):
            row[f"{prefix}_{label}"] = float(value)
    return row


class ScriptedInput:
    # Known task schedule for repeatable infrastructure checks; not a human model.
    segments = (
        (1.0, "FREE", [0, 0, 0]),
        (3.0, "APPROACH", [0.012, 0, 0]),
        (4.0, "PAINTING", [0.001, 0, 0.025]),
        (0.6, "RETRACT", [-0.03, 0, 0]),
        (0.3, "FREE", [0, 0, 0]),
        (1.2, "APPROACH", [0.012, 0, 0]),
        (3.0, "PAINTING", [0.001, 0.02, -0.02]),
        (1.0, "FREE", [0, 0, 0]),
    )
    duration = sum(s[0] for s in segments)

    def sample(self, t, dt, keyboard_clutch=False):
        end = 0.0
        for duration, task, v in self.segments:
            end += duration
            if t < end:
                return np.array(v, float), task != "FREE", task
        return np.zeros(3), False, "FREE"


class ReplayInput:
    def __init__(self, path):
        with Path(path).open(encoding="utf-8-sig", newline="") as f:
            self.rows = list(csv.DictReader(f))
        if not self.rows:
            raise ValueError("Empty replay")
        self.times = np.array([float(r["time_s"]) for r in self.rows])
        if not np.isfinite(self.times).all() or np.any(np.diff(self.times) <= 0):
            raise ValueError("Replay time must increase")
        self.duration = self.times[-1] + float(self.rows[-1]["dt_s"])

    def sample(self, t, dt, keyboard_clutch=False):
        i = np.searchsorted(self.times, t + 1e-8, side="right") - 1
        if i < 0 or t >= self.duration:
            return np.zeros(3), False, "FREE"
        r = self.rows[i]
        v = np.array([float(r[f"human_{a}_m_s"]) for a in "xyz"])
        return v, r["enabled"].lower() == "true", r["task"]
