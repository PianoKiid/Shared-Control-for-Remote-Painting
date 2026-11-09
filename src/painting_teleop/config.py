"""Configuration shared by the hardware bridge, physics runner and smoke test."""

import json
from pathlib import Path
import numpy as np
from .controller import Parameters


def load_config(path, root):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    Parameters(**config["controller"])
    if config["control_hz"] != 30:
        raise ValueError(
            "This checkpoint/preprocessing contract requires control_hz=30"
        )
    if config["physics_hz"] < 30 or config["physics_hz"] % 30:
        raise ValueError("physics_hz must be an integer multiple of control_hz")
    for key in (
        "joint_stiffness",
        "joint_damping",
        "joint_max_force",
        "contact_stiffness_N_m",
        "contact_damping_N_s_m",
        "max_translation_speed_m_s",
        "max_tracking_error_m",
        "max_force_N",
    ):
        if not np.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"{key} must be finite and positive")
    for key, size in [
        ("initial_joints_deg", 6),
        ("wall_center_yz_m", 2),
        ("wall_size_yz_m", 2),
        ("workspace_lower_m", 3),
        ("workspace_upper_m", 3),
    ]:
        v = np.asarray(config[key], float)
        if v.shape != (size,) or not np.isfinite(v).all():
            raise ValueError(f"Invalid {key}")
    if not np.isfinite(config["wall_x_m"]) or np.any(
        np.array(config["wall_size_yz_m"]) <= 0
    ):
        raise ValueError("Invalid wall geometry")
    if np.any(np.array(config["workspace_lower_m"]) >= config["workspace_upper_m"]):
        raise ValueError("Workspace lower must be less than upper")
    for key in ("robot_urdf", "checkpoint"):
        if not (Path(root) / config[key]).is_file():
            raise FileNotFoundError(Path(root) / config[key])
    if config["input"]["host"] != "127.0.0.1":
        raise ValueError("Run the UDP bridge on the simulator host (127.0.0.1)")
    return config
