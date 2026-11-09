"""Single entry point. --help and preflight do not import Isaac Sim."""

import argparse
import asyncio
import csv
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def parser():
    p = argparse.ArgumentParser(
        description="RB10 painting: Haply + Isaac Sim + replaceable shared control"
    )
    sub = p.add_subparsers(dest="action", required=True)
    bridge = sub.add_parser(
        "bridge", help="stream Haply input from Inverse Service 3.x"
    )
    bridge.add_argument("--url", default="ws://localhost:10001")
    bridge.add_argument("--port", type=int, default=15000)
    bridge.add_argument("--device-id")
    bridge.add_argument("--grip-id")
    bridge.add_argument("--force-key", choices=["values", "vector"], default="values")
    for name in ("isaac", "smoke", "preflight"):
        q = sub.add_parser(name)
        q.add_argument(
            "--config", type=Path, default=ROOT / "simulation/config/painting.json"
        )
        if name == "preflight":
            continue
        q.add_argument(
            "--condition", choices=["manual", "probability", "shared"], default="shared"
        )
        q.add_argument(
            "--input",
            choices=["haply", "scripted", "replay"],
            default="haply" if name == "isaac" else "scripted",
        )
        q.add_argument("--replay", type=Path)
        q.add_argument("--output", type=Path, default=ROOT / "results/teleop")
        q.add_argument("--duration", type=float)
        q.add_argument("--phase-delay-frames", type=int, default=0)
        q.add_argument(
            "--force-phase", choices=["FREE", "APPROACH", "PAINTING", "RETRACT"]
        )
        q.add_argument("--headless", action="store_true")
    compare = sub.add_parser(
        "compare", help="summarize independent-task metrics from trials"
    )
    compare.add_argument(
        "trials",
        type=Path,
        nargs="+",
        help="trial directories (metadata.json + samples.csv)",
    )
    compare.add_argument("--out", type=Path, required=True)
    return p


def main():
    args = parser().parse_args()
    if args.action == "bridge":
        from painting_teleop.haply_bridge import run_bridge

        try:
            asyncio.run(run_bridge(args))
        except KeyboardInterrupt:
            pass
        return
    if args.action == "compare":
        from painting_teleop.metrics import summarize

        results = []
        for directory in args.trials:
            metadata = json.loads(
                (directory / "metadata.json").read_text(encoding="utf-8")
            )
            with (directory / "samples.csv").open(encoding="utf-8", newline="") as f:
                metrics = summarize(
                    csv.DictReader(f),
                    metadata["config"]["controller"]["desired_force_N"],
                )
            summary = (
                json.loads((directory / "summary.json").read_text())
                if (directory / "summary.json").is_file()
                else {}
            )
            results.append(
                dict(
                    trial=str(directory),
                    backend=metadata["backend"],
                    condition=metadata["condition"],
                    status=summary.get("status", "unfinished"),
                    **metrics
                )
            )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        print(args.out)
        return
    from painting_teleop.config import load_config

    config = load_config(args.config, ROOT)
    if args.action == "preflight":
        import numpy as np
        from painting_teleop.geometry import RobotGeometry
        from painting_teleop.lstm import PhaseLSTM

        geometry = RobotGeometry(ROOT / config["robot_urdf"])
        PhaseLSTM(ROOT / config["checkpoint"])
        q = np.deg2rad(config["initial_joints_deg"])
        print(
            json.dumps(
                dict(
                    assets_and_model="OK",
                    initial_tcp_m=geometry.fk(q)[:3, 3].tolist(),
                    initial_roller_gap_mm=1000 * geometry.gap(q, config["wall_x_m"]),
                    isaacsim_available=importlib.util.find_spec("isaacsim") is not None,
                    websockets_available=importlib.util.find_spec("websockets")
                    is not None,
                    target_runtime="Isaac Sim 5.1; Haply Inverse Service 3.x",
                ),
                indent=2,
            )
        )
        return
    from painting_teleop.runtime import run_isaac, run_smoke

    (run_isaac if args.action == "isaac" else run_smoke)(args, config, ROOT)


if __name__ == "__main__":
    main()
