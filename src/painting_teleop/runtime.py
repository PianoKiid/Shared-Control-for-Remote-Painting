"""Run the same inference/controller pipeline with PhysX or a small smoke plant."""

from datetime import datetime, timezone
from dataclasses import replace
import math
from pathlib import Path
import platform
import time
import numpy as np

from .geometry import RobotGeometry
from .input import UDPInput
from .session import (
    ControlSession,
    ReplayInput,
    ScriptedInput,
    TrialLogger,
    model_hash,
    sample_row,
)


def make_source(args, config):
    if args.input == "haply":
        return UDPInput(**config["input"])
    if args.input == "replay":
        if not args.replay:
            raise ValueError("--input replay requires --replay samples.csv")
        return ReplayInput(args.replay)
    return ScriptedInput()


def make_logger(args, config, root, backend):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    directory = Path(args.output) / f"{stamp}_{backend}_{args.condition}"
    return TrialLogger(
        directory,
        dict(
            created_utc=stamp,
            backend=backend,
            condition=args.condition,
            input=args.input,
            replay=str(args.replay) if args.replay else None,
            phase_delay_frames=args.phase_delay_frames,
            force_phase=args.force_phase,
            config=config,
            checkpoint_sha256=model_hash(Path(root) / config["checkpoint"]),
            controller_sha256=model_hash(Path(__file__).with_name("controller.py")),
            source_sha256={
                p.name: model_hash(p) for p in Path(__file__).parent.glob("*.py")
            },
            python=platform.python_version(),
            platform=platform.platform(),
            force_source=(
                "PhysX roller-wall normal contact reaction, substep mean"
                if backend == "isaac"
                else "analytic spring smoke plant"
            ),
            force_axes="reaction in world -> negate -> rotate into recorded FT axes",
            task_source="operator buttons/keys or source script; independent of LSTM",
            evaluation_scope="virtual contact and control; paint deposition is not modeled",
        ),
    )


def source_sample(source, args, panel, t, dt):
    if args.input == "haply":
        human, enabled = source.sample(time.monotonic(), dt, panel.keyboard_clutch)
        return human, enabled, panel.task
    return source.sample(t, dt)


def duration_for(args, source):
    if args.duration is not None:
        if not math.isfinite(args.duration) or args.duration <= 0:
            raise ValueError("--duration must be finite and positive")
        return args.duration
    return getattr(source, "duration", math.inf)


def run_smoke(args, config, root):
    """A repeatable pipeline check with a synthetic compliant wall, not PhysX."""
    if args.input == "haply":
        raise ValueError("smoke uses --input scripted or replay")
    source = make_source(args, config)
    session = ControlSession(
        config, root, args.condition, args.phase_delay_frames, args.force_phase
    )
    geometry = RobotGeometry(Path(root) / config["robot_urdf"])
    q = np.deg2rad(config["initial_joints_deg"])
    initial = geometry.fk(q)[:3, 3]
    position = initial.copy()
    velocity = np.zeros(3)
    initial_gap = geometry.gap(q, config["wall_x_m"])
    logger = make_logger(args, config, root, "smoke")
    started = time.monotonic()
    dt = 1 / config["control_hz"]
    status = "completed"
    try:
        for i in range(math.ceil(duration_for(args, source) / dt)):
            t = i * dt
            human, enabled, task = source.sample(t, dt)
            gap = initial_gap - (position[0] - initial[0])
            force = (
                max(
                    0.0,
                    -gap * config["contact_stiffness_N_m"]
                    + config["contact_damping_N_s_m"] * velocity[0],
                )
                if gap <= 0
                else 0.0
            )
            ft = geometry.training_force(q, [-force, 0.0, 0.0])
            command, decision, probability, used, valid, bounded_human = session.step(
                t, position, ft, human, force, gap, enabled
            )
            fault = "force_limit" if force > config["max_force_N"] else ""
            if fault:
                command[:] = 0
                status = fault
            row = sample_row(
                t,
                dt,
                time.monotonic() - started,
                task,
                force,
                gap,
                position,
                bounded_human,
                command,
                decision,
                probability,
                used,
                enabled,
                valid,
                fault=fault,
                input_raw=human,
            )
            logger.write(row)
            if fault:
                break
            # A 50 ms first-order velocity servo provides a simple causal response.
            velocity += (1 - math.exp(-dt / 0.05)) * (command - velocity)
            if not enabled or not valid:
                velocity[:] = 0.0
            position = np.clip(
                position + velocity * dt,
                config["workspace_lower_m"],
                config["workspace_upper_m"],
            )
    except BaseException:
        status = "error"
        raise
    finally:
        logger.close(status)
    print(logger.directory)
    return logger.directory


def wait_until_playing(world, app, panel, live_source=None):
    """Process paused UI without advancing physics; return a terminal status."""
    while True:
        if panel.stop:
            return "operator_stop"
        if not app.is_running():
            return "window_closed"
        if world.is_stopped():
            return "timeline_stopped"
        if world.is_playing():
            return None
        if live_source is not None:
            live_source.buffer.active = False
            live_source.buffer.reset_pending = True
        panel.keyboard_clutch = False
        world.render()


def run_isaac(args, config, root):
    try:
        from isaacsim import SimulationApp
    except ImportError as exc:
        raise RuntimeError(
            "Run isaac with the Isaac Sim 5.1 python.bat/python.sh, not ordinary Python. See simulation/USAGE_ko.md"
        ) from exc
    app = SimulationApp({"headless": args.headless})
    logger = source = panel = scene = None
    status = "error"
    try:
        from .isaac_scene import IsaacScene, OperatorPanel, TimelineStopped

        scene = IsaacScene(config, root)
        panel = OperatorPanel(args.condition, args.headless)
        source = make_source(args, config)
        duration = duration_for(args, source)
        session = ControlSession(
            config, root, args.condition, args.phase_delay_frames, args.force_phase
        )
        logger = make_logger(args, config, root, "isaac")
        q = scene.joints()
        target = scene.geometry.fk(q)[:3, 3].copy()
        orientation = scene.geometry.fk(q)[:3, :3].copy()
        reaction = np.zeros(3)
        dt = 1 / config["control_hz"]
        substeps = config["physics_hz"] // config["control_hz"]
        started = time.monotonic()
        deadline = started
        tick = 0
        peak_force = 0.0
        status = "completed"
        while app.is_running() and tick * dt < duration:
            stopped = wait_until_playing(
                scene.world, app, panel, source if args.input == "haply" else None
            )
            if stopped:
                status = stopped
                break
            t = tick * dt
            q = scene.joints()
            position = scene.geometry.fk(q)[:3, 3]
            gap = scene.geometry.gap(q, config["wall_x_m"])
            force = max(0.0, -float(reaction[0]))
            tracking = float(np.linalg.norm(target - position))
            human, enabled, task = source_sample(source, args, panel, t, dt)
            command, decision, probability, used, valid, bounded_human = session.step(
                t,
                position,
                scene.geometry.training_force(q, reaction),
                human,
                force,
                gap,
                enabled,
            )
            requested = command.copy()
            fault = ""
            if max(force, peak_force) > config["max_force_N"]:
                fault = "force_limit"
            elif tracking > config["max_tracking_error_m"]:
                fault = "tracking_limit"
            active = enabled and valid and not fault
            if active:
                proposed = np.clip(
                    target + command * dt,
                    config["workspace_lower_m"],
                    config["workspace_upper_m"],
                )
                solved, error = scene.geometry.ik(q, proposed, orientation)
                if error > 0.002 or np.max(np.abs(solved - q)) > 0.1:
                    fault = "ik_or_joint_step_limit"
                else:
                    command = (proposed - target) / dt
                    target = proposed
                    scene.apply(solved)
            if not active or fault:
                target = position.copy()
                command = np.zeros(3)
                decision = replace(decision, command=0.0, authority=0.0, mode="hold")
                scene.apply(q)
            row = sample_row(
                t,
                dt,
                time.monotonic() - started,
                task,
                force,
                gap,
                position,
                bounded_human,
                command,
                decision,
                probability,
                used,
                enabled,
                valid,
                tracking,
                fault,
                human,
            )
            row["force_peak_N"] = peak_force
            for axis, value in zip("xyz", requested):
                row[f"requested_{axis}_m_s"] = float(value)
            for name, value in zip(
                ("base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"), q
            ):
                row[f"joint_{name}_rad"] = float(value)
            logger.write(row)
            panel.task = task
            panel.update(t, force, gap, decision, probability, enabled and valid)
            if tick % 30 == 0:
                print(
                    f"{t:6.1f}s {task:9s} F={force:6.2f}N gap={gap*1000:6.2f}mm alpha={decision.authority:.2f} {decision.mode}",
                    flush=True,
                )
            if fault:
                status = fault
                break
            reactions = []
            before_physics = scene.world.current_time
            try:
                for step in range(substeps):
                    # A native Pause may arrive during rendering. Finish this same
                    # control interval after Play, without inventing physics time.
                    stopped = wait_until_playing(
                        scene.world,
                        app,
                        panel,
                        source if args.input == "haply" else None,
                    )
                    if stopped:
                        raise TimelineStopped(stopped)
                    reactions.append(
                        scene.step(render=not args.headless and step % 2 == 0)
                    )
            except TimelineStopped as stopped:
                status = stopped.args[0] if stopped.args else "timeline_stopped"
                break
            if abs(scene.world.current_time - before_physics - dt) > 1e-6:
                raise RuntimeError(
                    "Physics time did not advance by exactly one control interval"
                )
            reaction = np.mean(reactions, axis=0)
            peak_force = max(0.0, max(-r[0] for r in reactions))
            tick += 1
            if args.input == "haply":
                # One control step per new wall-clock interval; never catch up in bursts.
                deadline = max(deadline + dt, time.monotonic())
                time.sleep(max(0.0, deadline - time.monotonic()))
        if not app.is_running() and tick * dt < duration:
            status = "window_closed"
    except KeyboardInterrupt:
        status = "interrupted"
    except BaseException:
        status = "error"
        raise
    finally:
        if logger is not None:
            logger.close(status)
            print(f"Trial {status}: {logger.directory}", flush=True)
        if source is not None and hasattr(source, "close"):
            source.close()
        if panel is not None:
            panel.close()
        if scene is not None and scene.world.is_playing():
            scene.world.stop()
        app.close()
    return logger.directory if logger else None
