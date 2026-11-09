"""Evaluation from independent task markers, with time-weighted denominators."""

import math


def summarize(rows, target_force=10.0):
    rows = list(rows)
    paint = [r for r in rows if r.get("task") == "PAINTING"]
    duration = sum(float(r["dt_s"]) for r in paint)

    def weighted(fn):
        return (
            sum(float(r["dt_s"]) * fn(r) for r in paint) / duration
            if duration
            else None
        )

    loss_events = 0
    recoveries = []
    start = None
    elapsed = 0.0
    for r in rows:
        dt = float(r["dt_s"])
        elapsed += dt
        if r.get("task") != "PAINTING":
            start = None
            continue
        if float(r["force_N"]) < 1.0:
            if start is None:
                start = elapsed - dt
                loss_events += 1
        elif start is not None:
            recoveries.append(elapsed - dt - start)
            start = None
    mse = weighted(lambda r: (float(r["force_N"]) - target_force) ** 2)
    contact_path = 0.0
    for before, after in zip(rows, rows[1:]):
        if all(
            r.get("task") == "PAINTING" and float(r["force_N"]) >= 1.0
            for r in (before, after)
        ):
            contact_path += math.hypot(
                float(after["y_m"]) - float(before["y_m"]),
                float(after["z_m"]) - float(before["z_m"]),
            )

    def active(r):
        return all(
            str(r.get(k, True)).lower() in ("true", "1")
            for k in ("enabled", "feature_valid")
        ) and not r.get("fault")

    return dict(
        samples=len(rows),
        duration_s=sum(float(r["dt_s"]) for r in rows),
        painting_duration_s=duration,
        painting_force_rmse_N=math.sqrt(mse) if mse is not None else None,
        painting_force_mean_N=weighted(lambda r: float(r["force_N"])),
        painting_below_1N_pct=weighted(lambda r: 100.0 * (float(r["force_N"]) < 1.0)),
        painting_within_target_2N_pct=weighted(
            lambda r: 100.0 * (abs(float(r["force_N"]) - target_force) <= 2.0)
        ),
        painting_gap_mean_mm=weighted(lambda r: 1000.0 * max(0.0, float(r["gap_m"]))),
        painting_disabled_pct=weighted(lambda r: 100.0 * (not active(r))),
        painting_contact_path_m=contact_path,
        tracking_error_max_mm=1000
        * max((float(r.get("tracking_error_m", 0.0)) for r in rows), default=0.0),
        contact_loss_events=loss_events,
        recovered_events=len(recoveries),
        mean_recovery_s=sum(recoveries) / len(recoveries) if recoveries else None,
        withdrawal_interference_mm=1000
        * sum(
            float(r["dt_s"])
            * max(0.0, float(r["command_normal_m_s"]) - float(r["human_normal_m_s"]))
            for r in rows
            if r.get("task") == "RETRACT" and float(r["human_normal_m_s"]) < 0
        ),
        fault_samples=sum(bool(r.get("fault")) for r in rows),
        marker_source="operator or scripted task; never inferred phase",
        evaluation_scope="virtual contact/teleoperation metrics; coating quality is not simulated",
    )
