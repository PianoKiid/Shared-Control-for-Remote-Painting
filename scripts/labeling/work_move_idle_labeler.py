#!/usr/bin/env python3
"""Prepare Sub12-14 MCAP files, serve a manual WORK/MOVE/IDLE editor,
and export interval metrics plus model-ready data.

The raw MCAP files are never modified.  Communication dropouts are removed
before labeling; manual IDLE labels are retained in the audit files but are
excluded from the model-ready NPZ files and from distance/speed metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPS = PROJECT_ROOT / ".analysis_deps"
if DEPS.exists():
    sys.path.insert(0, str(DEPS))

from mcap.records import Channel, Message, Schema  # noqa: E402
from mcap.stream_reader import StreamReader  # noqa: E402
from mcap_ros2.decoder import DecoderFactory  # noqa: E402


SOURCE_ROOT = Path(r"D:\SNUCEM\PROJECTS\다부처\원격도장작업실험\DATA\subjects")
WIDE_SOURCE = Path(r"D:\SNUCEM\PROJECTS\다부처\원격도장작업실험\DATA\원격도장작업실험_0720_Wide Format.xlsx")
OUT_ROOT = PROJECT_ROOT / "results" / "labeling" / "work_move_idle_12_14"
TRIAL_DATA_DIR = PROJECT_ROOT / "data" / "interim" / "work_move_idle_12_14"
LABEL_DIR = PROJECT_ROOT / "data" / "annotations" / "work_move_idle_12_14"
METRIC_DIR = OUT_ROOT / "metrics"
MODEL_DIR = PROJECT_ROOT / "data" / "processed" / "work_move_idle_v1"
EXCEL_OUT = PROJECT_ROOT / "results" / "spreadsheets" / "원격도장작업실험_0720_Wide Format_12-14추가.xlsx"
HTML_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
UPDATE_WIDE_SCRIPT = PROJECT_ROOT / "scripts" / "spreadsheets" / "update_wide_format_12_14.mjs"
PYTHON_EXE = Path(r"C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
NODE_EXE = Path(r"C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")

LABEL_TO_ID = {"WORK": 0, "MOVE": 1, "IDLE": 2}
ID_TO_LABEL = {v: k for k, v in LABEL_TO_ID.items()}
TOPICS = {"/rb/ee_pose", "/rb/ee_wrench", "/rb/teleop_delta", "/rb/teleop_buttons"}


TRIAL_SOURCES: dict[str, list[Path]] = {
    "12-VP": [SOURCE_ROOT / "12" / "12-0 (1)" / "12-VP" / "12-01_0.mcap"],
    "12-MS": [SOURCE_ROOT / "12" / "12-0 (1)" / "12-MS" / "12-02_0.mcap"],
    "12-VS": [SOURCE_ROOT / "12" / "12-0 (1)" / "12-VS" / "12-03_0.mcap"],
    "12-MP": [SOURCE_ROOT / "12" / "12-0 (1)" / "12-MP" / "12-04_0.mcap"],
    "13-MP": [SOURCE_ROOT / "13" / "13-MP" / "13-01_0.mcap"],
    "13-MS": [SOURCE_ROOT / "13" / "13-MS" / "13-02_0.mcap"],
    "13-VS": [SOURCE_ROOT / "13" / "13-VS" / "13-03_0.mcap"],
    "13-VP": [SOURCE_ROOT / "13" / "13-VP" / "13-04_0.mcap"],
    "14-VS": [SOURCE_ROOT / "14" / "14-VS" / "14-01_0.mcap"],
    "14-VP": [SOURCE_ROOT / "14" / "14-VP" / "14-02_0.mcap"],
    "14-MS": [SOURCE_ROOT / "14" / "14-MS" / "14-03_0.mcap"],
    "14-MP": [
        SOURCE_ROOT / "14" / "14-MP" / "14-04_0.mcap",
        SOURCE_ROOT / "14" / "14-MP-2" / "14-04_2_0.mcap",
    ],
}


@dataclass
class PartData:
    stamp_ns: np.ndarray
    position: np.ndarray
    wrench: np.ndarray
    teleop_stamp_ns: np.ndarray
    button_stamp_ns: np.ndarray
    button_valid: np.ndarray


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def stamp_ns_from_header(message: Any, fallback_ns: int) -> int:
    try:
        stamp = message.header.stamp
        return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
    except Exception:
        return int(fallback_ns)


def _sorted_array(items: list[tuple[int, Any]], width: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    if not items:
        values = np.empty((0, width), dtype=np.float64) if width else np.empty((0,), dtype=np.float64)
        return np.empty((0,), dtype=np.int64), values
    items.sort(key=lambda item: item[0])
    stamps = np.asarray([item[0] for item in items], dtype=np.int64)
    values = np.asarray([item[1] for item in items], dtype=np.float64)
    return stamps, values


def read_mcap_part(path: Path) -> PartData:
    """Stream records instead of trusting the MCAP footer.

    This also reads 13-VP and 14-VP, whose trailing index/footer is damaged.
    """
    schemas: dict[int, Schema] = {}
    channels: dict[int, Channel] = {}
    decoders: dict[int, Any] = {}
    decoder_factory = DecoderFactory()
    poses: list[tuple[int, tuple[float, float, float]]] = []
    wrenches: list[tuple[int, tuple[float, float, float, float, float, float]]] = []
    teleop: list[tuple[int, float]] = []
    buttons: list[tuple[int, float]] = []
    button_valid: list[tuple[int, float]] = []

    with path.open("rb") as stream:
        try:
            for record in StreamReader(stream, emit_chunks=False).records:
                if isinstance(record, Schema):
                    schemas[record.id] = record
                    continue
                if isinstance(record, Channel):
                    channels[record.id] = record
                    continue
                if not isinstance(record, Message):
                    continue
                channel = channels.get(record.channel_id)
                if channel is None or channel.topic not in TOPICS:
                    continue
                decode = decoders.get(channel.id)
                if decode is None:
                    decode = decoder_factory.decoder_for(channel.message_encoding, schemas.get(channel.schema_id))
                    decoders[channel.id] = decode
                if decode is None:
                    continue
                try:
                    msg = decode(record.data)
                except Exception:
                    continue
                if channel.topic == "/rb/ee_pose":
                    t = stamp_ns_from_header(msg, record.log_time)
                    p = msg.pose.position
                    poses.append((t, (float(p.x), float(p.y), float(p.z))))
                elif channel.topic == "/rb/ee_wrench":
                    t = stamp_ns_from_header(msg, record.log_time)
                    f = msg.wrench.force
                    q = msg.wrench.torque
                    wrenches.append((t, (float(f.x), float(f.y), float(f.z), float(q.x), float(q.y), float(q.z))))
                elif channel.topic == "/rb/teleop_delta":
                    t = stamp_ns_from_header(msg, record.log_time)
                    teleop.append((t, 1.0))
                elif channel.topic == "/rb/teleop_buttons":
                    try:
                        payload = json.loads(msg.data)
                        t = int(float(payload.get("stamp_sec", record.log_time / 1e9)) * 1e9)
                        valid = bool(payload.get("wvg_valid", True))
                    except Exception:
                        t, valid = int(record.log_time), True
                    buttons.append((t, 1.0))
                    button_valid.append((t, 1.0 if valid else 0.0))
        except Exception as exc:
            # A missing/corrupt footer is expected in two recordings.  All
            # message records yielded before EOF remain valid and are kept.
            if not poses:
                raise RuntimeError(f"MCAP를 읽지 못했습니다: {path}\n{exc}") from exc

    pose_t, position = _sorted_array(poses, 3)
    wrench_t, wrench = _sorted_array(wrenches, 6)
    teleop_t, _ = _sorted_array(teleop)
    button_t, _ = _sorted_array(buttons)
    valid_t, valid_v = _sorted_array(button_valid)
    if not np.array_equal(button_t, valid_t):
        raise RuntimeError(f"버튼 타임스탬프가 일치하지 않습니다: {path}")
    if len(pose_t) < 2:
        raise RuntimeError(f"EE pose 데이터가 부족합니다: {path}")
    return PartData(pose_t, position, _align_nearest(pose_t, wrench_t, wrench, 0.020), teleop_t, button_t, valid_v.astype(bool))


def _align_nearest(target_t: np.ndarray, source_t: np.ndarray, values: np.ndarray, max_age_s: float) -> np.ndarray:
    width = values.shape[1] if values.ndim == 2 else 1
    out = np.full((len(target_t), width), np.nan, dtype=np.float64)
    if len(source_t) == 0:
        return out
    right = np.searchsorted(source_t, target_t, side="left")
    left = np.clip(right - 1, 0, len(source_t) - 1)
    right = np.clip(right, 0, len(source_t) - 1)
    choose_right = np.abs(source_t[right] - target_t) < np.abs(source_t[left] - target_t)
    idx = np.where(choose_right, right, left)
    ok = np.abs(source_t[idx] - target_t) <= int(max_age_s * 1e9)
    out[ok] = values[idx[ok]].reshape((-1, width))
    return out


def past_age_and_value(target_t: np.ndarray, source_t: np.ndarray, values: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray | None]:
    idx = np.searchsorted(source_t, target_t, side="right") - 1
    ok = idx >= 0
    clipped = np.clip(idx, 0, max(len(source_t) - 1, 0))
    age = np.full(len(target_t), np.inf, dtype=np.float64)
    out_values = None
    if len(source_t):
        age[ok] = (target_t[ok] - source_t[clipped[ok]]) / 1e9
        if values is not None:
            out_values = np.zeros(len(target_t), dtype=values.dtype)
            out_values[ok] = values[clipped[ok]]
    elif values is not None:
        out_values = np.zeros(len(target_t), dtype=values.dtype)
    return age, out_values


def contiguous_true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(changes[i]), int(changes[i + 1] - 1)) for i in range(0, len(changes), 2)]


def valid_runs(part: PartData) -> tuple[list[tuple[int, int]], dict[str, int]]:
    pose_t = part.stamp_ns
    dt = np.diff(pose_t, prepend=pose_t[0]) / 1e9
    pose_continuous = (dt <= 0.100) & (dt >= 0)
    pose_continuous[0] = True
    wrench_ok = np.isfinite(part.wrench).all(axis=1)
    teleop_age, _ = past_age_and_value(pose_t, part.teleop_stamp_ns)
    button_age, button_valid = past_age_and_value(pose_t, part.button_stamp_ns, part.button_valid)
    valid = pose_continuous & wrench_ok & (teleop_age >= 0) & (teleop_age < 0.100) & (button_age >= 0) & (button_age < 0.100)
    if button_valid is not None:
        valid &= button_valid

    raw_runs = contiguous_true_runs(valid)
    kept: list[tuple[int, int]] = []
    for start, end in raw_runs:
        start_t = pose_t[start] + (1_000_000_000 if start > 0 else 0)
        end_t = pose_t[end] - (500_000_000 if end < len(pose_t) - 1 else 0)
        trimmed_start = int(np.searchsorted(pose_t, start_t, side="left"))
        trimmed_end = int(np.searchsorted(pose_t, end_t, side="right") - 1)
        if trimmed_end > trimmed_start and (pose_t[trimmed_end] - pose_t[trimmed_start]) >= 2_000_000_000:
            kept.append((trimmed_start, trimmed_end))
    stats = {
        "pose_frames_raw": int(len(pose_t)),
        "pose_frames_valid": int(sum(end - start + 1 for start, end in kept)),
        "raw_valid_runs": int(len(raw_runs)),
        "kept_runs": int(len(kept)),
        "frames_removed": int(len(pose_t) - sum(end - start + 1 for start, end in kept)),
    }
    return kept, stats


def array_round(values: np.ndarray, digits: int) -> list[Any]:
    return np.round(values, digits).tolist()


def preprocess_trial(trial_id: str, source_paths: list[Path]) -> dict[str, Any]:
    all_stamp: list[np.ndarray] = []
    all_time: list[np.ndarray] = []
    all_pos: list[np.ndarray] = []
    all_wrench: list[np.ndarray] = []
    all_speed: list[np.ndarray] = []
    all_segment: list[np.ndarray] = []
    all_file_part: list[np.ndarray] = []
    segments: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    cursor = 0
    ui_offset = 0.0
    global_segment = 0

    for part_idx, source_path in enumerate(source_paths):
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        part = read_mcap_part(source_path)
        runs, stats = valid_runs(part)
        stats.update({"source": str(source_path), "file_part": part_idx + 1})
        source_stats.append(stats)
        for run_idx, (start, end) in enumerate(runs):
            sl = slice(start, end + 1)
            stamp = part.stamp_ns[sl]
            pos = part.position[sl]
            wrench = part.wrench[sl]
            local_t = (stamp - stamp[0]) / 1e9
            speed = np.zeros(len(stamp), dtype=np.float64)
            if len(stamp) > 1:
                step_dt = np.diff(stamp) / 1e9
                step_dist = np.linalg.norm(np.diff(pos, axis=0), axis=1)
                speed[1:] = np.divide(step_dist, step_dt, out=np.zeros_like(step_dist), where=step_dt > 0)
            ui_time = ui_offset + local_t
            global_segment += 1
            all_stamp.append(stamp)
            all_time.append(ui_time)
            all_pos.append(pos)
            all_wrench.append(wrench)
            all_speed.append(speed)
            all_segment.append(np.full(len(stamp), global_segment, dtype=np.int32))
            all_file_part.append(np.full(len(stamp), part_idx + 1, dtype=np.int16))
            segments.append({
                "segment_id": global_segment,
                "file_part": part_idx + 1,
                "source_name": source_path.name,
                "source_run": run_idx + 1,
                "start_index": cursor,
                "end_index": cursor + len(stamp) - 1,
                "start_ui_s": float(ui_time[0]),
                "end_ui_s": float(ui_time[-1]),
                "duration_s": float(local_t[-1]),
                "frame_count": int(len(stamp)),
            })
            cursor += len(stamp)
            ui_offset = float(ui_time[-1] + 0.25)

    if not all_stamp:
        raise RuntimeError(f"유효한 연속 구간이 없습니다: {trial_id}")
    stamp_ns = np.concatenate(all_stamp)
    ui_time_s = np.concatenate(all_time)
    position = np.concatenate(all_pos)
    wrench = np.concatenate(all_wrench)
    speed = np.concatenate(all_speed)
    segment_id = np.concatenate(all_segment)
    file_part = np.concatenate(all_file_part)

    TRIAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        TRIAL_DATA_DIR / f"{trial_id}.npz",
        stamp_ns=stamp_ns,
        ui_time_s=ui_time_s,
        position_m=position,
        wrench=wrench,
        speed_m_s=speed,
        segment_id=segment_id,
        file_part=file_part,
    )
    player = {
        "trial_id": trial_id,
        "subject": int(trial_id.split("-")[0]),
        "interface": trial_id.split("-")[1],
        "frame_count": int(len(stamp_ns)),
        "duration_ui_s": float(ui_time_s[-1]),
        "time_s": array_round(ui_time_s, 4),
        "position_m": array_round(position, 6),
        "force_N": array_round(wrench[:, :3], 4),
        "speed_m_s": array_round(speed, 5),
        "segment_id": segment_id.tolist(),
        "file_part": file_part.tolist(),
        "segments": segments,
        "sources": [str(path) for path in source_paths],
        "preprocessing": {
            "pose_gap_threshold_s": 0.100,
            "wrench_tolerance_s": 0.020,
            "teleop_max_past_age_s": 0.100,
            "pre_gap_exclusion_s": 0.500,
            "post_reconnect_exclusion_s": 1.000,
            "minimum_segment_s": 2.000,
            "source_stats": source_stats,
        },
    }
    atomic_json(TRIAL_DATA_DIR / f"{trial_id}.json", player)
    label_path = LABEL_DIR / f"{trial_id}.labels.json"
    if not label_path.exists():
        atomic_json(label_path, {
            "trial_id": trial_id,
            "frame_count": int(len(stamp_ns)),
            "labels": [],
            "updated_at": None,
            "note": "초기 상태: 모든 유효 프레임이 UNLABELED입니다.",
        })
    return {
        "trial_id": trial_id,
        "frame_count": int(len(stamp_ns)),
        "duration_ui_s": round(float(ui_time_s[-1]), 3),
        "segment_count": int(len(segments)),
        "source_count": len(source_paths),
        "appended_sources": len(source_paths) > 1,
        "sources": [str(path) for path in source_paths],
    }


def load_intervals(trial_id: str) -> list[dict[str, Any]]:
    path = LABEL_DIR / f"{trial_id}.labels.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("labels", [])


def labels_to_array(frame_count: int, intervals: list[dict[str, Any]]) -> np.ndarray:
    labels = np.full(frame_count, -1, dtype=np.int8)
    for item in intervals:
        label = str(item["label"]).upper()
        if label not in LABEL_TO_ID:
            raise ValueError(f"알 수 없는 라벨: {label}")
        start, end = int(item["start_index"]), int(item["end_index"])
        if start < 0 or end < start or end >= frame_count:
            raise ValueError(f"잘못된 프레임 범위: {start}-{end}")
        labels[start : end + 1] = LABEL_TO_ID[label]
    return labels


def array_to_intervals(labels: np.ndarray) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    start = 0
    while start < len(labels):
        value = int(labels[start])
        end = start
        while end + 1 < len(labels) and int(labels[end + 1]) == value:
            end += 1
        if value in ID_TO_LABEL:
            result.append({"start_index": start, "end_index": end, "label": ID_TO_LABEL[value]})
        start = end + 1
    return result


def write_interval_csv(trial_id: str, intervals: list[dict[str, Any]], data: Any) -> None:
    METRIC_DIR.mkdir(parents=True, exist_ok=True)
    with (LABEL_DIR / f"{trial_id}.intervals.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["trial_id", "label", "start_index", "end_index", "start_time_s", "end_time_s", "frame_count"])
        for item in intervals:
            start, end = int(item["start_index"]), int(item["end_index"])
            writer.writerow([trial_id, item["label"], start, end, float(data["ui_time_s"][start]), float(data["ui_time_s"][end]), end - start + 1])


def split_labeled_episodes(labels: np.ndarray, segment_id: np.ndarray) -> Iterable[tuple[int, int, int]]:
    start = 0
    n = len(labels)
    while start < n:
        value = int(labels[start])
        segment = int(segment_id[start])
        end = start
        while end + 1 < n and int(labels[end + 1]) == value and int(segment_id[end + 1]) == segment:
            end += 1
        if value in (LABEL_TO_ID["WORK"], LABEL_TO_ID["MOVE"]):
            yield start, end, value
        start = end + 1


def finalize_trial(trial_id: str) -> dict[str, Any]:
    raw = np.load(TRIAL_DATA_DIR / f"{trial_id}.npz")
    intervals = load_intervals(trial_id)
    labels = labels_to_array(len(raw["stamp_ns"]), intervals)
    canonical_intervals = array_to_intervals(labels)
    write_interval_csv(trial_id, canonical_intervals, raw)

    metric_rows: list[dict[str, Any]] = []
    by_label: dict[str, list[dict[str, Any]]] = {"WORK": [], "MOVE": []}
    for start, end, label_id in split_labeled_episodes(labels, raw["segment_id"]):
        label = ID_TO_LABEL[label_id]
        position = raw["position_m"][start : end + 1]
        stamps = raw["stamp_ns"][start : end + 1]
        distance = float(np.linalg.norm(np.diff(position, axis=0), axis=1).sum()) if len(position) > 1 else 0.0
        duration = float((int(stamps[-1]) - int(stamps[0])) / 1e9) if len(stamps) > 1 else 0.0
        avg_speed = distance / duration if duration > 0 else 0.0
        row = {
            "trial_id": trial_id,
            "label": label,
            "start_index": start,
            "end_index": end,
            "segment_id": int(raw["segment_id"][start]),
            "file_part": int(raw["file_part"][start]),
            "frame_count": end - start + 1,
            "duration_sec": duration,
            "distance_m": distance,
            "avg_speed_m_s": avg_speed,
        }
        metric_rows.append(row)
        by_label[label].append(row)

    METRIC_DIR.mkdir(parents=True, exist_ok=True)
    with (METRIC_DIR / f"{trial_id}.segment_metrics.csv").open("w", newline="", encoding="utf-8-sig") as f:
        columns = ["trial_id", "label", "start_index", "end_index", "segment_id", "file_part", "frame_count", "duration_sec", "distance_m", "avg_speed_m_s"]
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(metric_rows)

    summary: dict[str, Any] = {
        "trial_id": trial_id,
        "subject": int(trial_id.split("-")[0]),
        "interface": trial_id.split("-")[1],
        "frame_count": int(len(labels)),
        "labeled_frames": int(np.sum(labels >= 0)),
        "unlabeled_frames": int(np.sum(labels < 0)),
        "complete": bool(np.all(labels >= 0)),
        "updated_at": now_iso(),
    }
    for label in ("WORK", "MOVE"):
        rows = by_label[label]
        prefix = label.lower()
        summary[f"{prefix}_interval_count"] = len(rows)
        summary[f"average_{prefix}_distance_m"] = float(np.mean([row["distance_m"] for row in rows])) if rows else None
        summary[f"average_{prefix}_speed_m_s"] = float(np.mean([row["avg_speed_m_s"] for row in rows])) if rows else None
        summary[f"total_{prefix}_distance_m"] = float(sum(row["distance_m"] for row in rows))

    keep = np.isin(labels, [LABEL_TO_ID["WORK"], LABEL_TO_ID["MOVE"]])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        MODEL_DIR / f"{trial_id}.npz",
        stamp_ns=raw["stamp_ns"][keep],
        time_s=raw["ui_time_s"][keep],
        position_m=raw["position_m"][keep],
        wrench=raw["wrench"][keep],
        speed_m_s=raw["speed_m_s"][keep],
        phase_id=labels[keep],
        phase_name=np.asarray([ID_TO_LABEL[int(value)] for value in labels[keep]]),
        source_segment_id=raw["segment_id"][keep],
        source_file_part=raw["file_part"][keep],
        note="IDLE and UNLABELED frames excluded; segment/file boundaries must reset sequence state.",
    )
    atomic_json(METRIC_DIR / f"{trial_id}.summary.json", summary)
    return summary


def update_excel(metric_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    metric_payload = {
        "generated_at": now_iso(),
        "source_workbook": str(WIDE_SOURCE),
        "output_workbook": str(EXCEL_OUT),
        "trials": metric_summaries,
    }
    metric_json = METRIC_DIR / "wide_format_metrics.json"
    atomic_json(metric_json, metric_payload)
    if not NODE_EXE.exists():
        raise RuntimeError(f"Node 실행 파일이 없습니다: {NODE_EXE}")
    completed = subprocess.run(
        [str(NODE_EXE), str(UPDATE_WIDE_SCRIPT), str(metric_json)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"엑셀 업데이트 실패\n{completed.stdout}\n{completed.stderr}")
    return {"output": str(EXCEL_OUT), "log": completed.stdout.strip()}


def finalize_all() -> dict[str, Any]:
    summaries = [finalize_trial(trial_id) for trial_id in TRIAL_SOURCES]
    with (METRIC_DIR / "summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        columns = [
            "trial_id", "subject", "interface", "complete", "frame_count", "labeled_frames", "unlabeled_frames",
            "work_interval_count", "average_work_distance_m", "average_work_speed_m_s", "total_work_distance_m",
            "move_interval_count", "average_move_distance_m", "average_move_speed_m_s", "total_move_distance_m", "updated_at",
        ]
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summaries)
    excel = update_excel(summaries)
    complete_count = sum(1 for item in summaries if item["complete"])
    result = {
        "ok": True,
        "complete_trials": complete_count,
        "total_trials": len(summaries),
        "incomplete_trials": [item["trial_id"] for item in summaries if not item["complete"]],
        "excel_output": excel["output"],
        "metric_summary": str(METRIC_DIR / "summary.csv"),
        "model_output": str(MODEL_DIR),
    }
    atomic_json(OUT_ROOT / "last_export.json", result)
    return result


def progress_for(trial_id: str, frame_count: int) -> dict[str, Any]:
    intervals = load_intervals(trial_id)
    labels = labels_to_array(frame_count, intervals)
    counts = {label: int(np.sum(labels == value)) for label, value in LABEL_TO_ID.items()}
    counts["UNLABELED"] = int(np.sum(labels < 0))
    return {
        "labeled_frames": int(np.sum(labels >= 0)),
        "unlabeled_frames": counts["UNLABELED"],
        "percent": round(100 * float(np.sum(labels >= 0)) / frame_count, 1),
        "counts": counts,
        "updated_at": json.loads((LABEL_DIR / f"{trial_id}.labels.json").read_text(encoding="utf-8")).get("updated_at"),
    }


def prepare_all(force: bool = False) -> dict[str, Any]:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_trials = []
    for trial_id, paths in TRIAL_SOURCES.items():
        json_path = TRIAL_DATA_DIR / f"{trial_id}.json"
        npz_path = TRIAL_DATA_DIR / f"{trial_id}.npz"
        if force or not json_path.exists() or not npz_path.exists():
            print(f"[가공] {trial_id}", flush=True)
            item = preprocess_trial(trial_id, paths)
        else:
            cached = json.loads(json_path.read_text(encoding="utf-8"))
            item = {
                "trial_id": trial_id,
                "frame_count": cached["frame_count"],
                "duration_ui_s": round(cached["duration_ui_s"], 3),
                "segment_count": len(cached["segments"]),
                "source_count": len(paths),
                "appended_sources": len(paths) > 1,
                "sources": [str(path) for path in paths],
            }
        item["progress"] = progress_for(trial_id, item["frame_count"])
        manifest_trials.append(item)
    manifest = {
        "version": 1,
        "created_at": now_iso(),
        "labels": ["WORK", "MOVE", "IDLE"],
        "unlabeled_is_draft_only": True,
        "idle_excluded_from_model_and_metrics": True,
        "metric_definition": {
            "distance": "구간 안 연속 EE position의 3D 유클리드 거리 합",
            "interval_speed": "구간 거리 / (마지막 timestamp - 첫 timestamp)",
            "average_distance": "같은 상태 구간별 distance의 산술평균",
            "average_speed": "같은 상태 구간별 avg_speed의 산술평균",
            "boundary_rule": "통신 단절/파일 경계/IDLE/UNLABELED를 가로질러 거리를 연결하지 않음",
        },
        "excel_source": str(WIDE_SOURCE),
        "excel_output": str(EXCEL_OUT),
        "trials": manifest_trials,
    }
    atomic_json(OUT_ROOT / "manifest.json", manifest)
    return manifest


class LabelServer(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkMoveIdleLabeler/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[웹] {self.address_string()} {fmt % args}")

    def send_json(self, obj: Any, status: int = 200) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            self.send_file(HTML_PATH, "text/html; charset=utf-8")
            return
        if path == "/api/manifest":
            manifest = json.loads((OUT_ROOT / "manifest.json").read_text(encoding="utf-8"))
            for item in manifest["trials"]:
                item["progress"] = progress_for(item["trial_id"], item["frame_count"])
            self.send_json(manifest)
            return
        if path.startswith("/api/trial/"):
            trial_id = path.rsplit("/", 1)[-1]
            if trial_id not in TRIAL_SOURCES:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file(TRIAL_DATA_DIR / f"{trial_id}.json", "application/json; charset=utf-8")
            return
        if path.startswith("/api/labels/"):
            trial_id = path.rsplit("/", 1)[-1]
            if trial_id not in TRIAL_SOURCES:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file(LABEL_DIR / f"{trial_id}.labels.json", "application/json; charset=utf-8")
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if path == "/api/save-labels":
                trial_id = str(body.get("trial_id", ""))
                if trial_id not in TRIAL_SOURCES:
                    raise ValueError("알 수 없는 trial입니다.")
                frame_count = int(json.loads((TRIAL_DATA_DIR / f"{trial_id}.json").read_text(encoding="utf-8"))["frame_count"])
                incoming = body.get("labels", [])
                labels = labels_to_array(frame_count, incoming)
                canonical = array_to_intervals(labels)
                payload = {
                    "trial_id": trial_id,
                    "frame_count": frame_count,
                    "labels": canonical,
                    "updated_at": now_iso(),
                    "note": "IDLE은 감사용 라벨에 남지만 모델 입력과 작업/이동 지표에서는 제외됩니다.",
                }
                atomic_json(LABEL_DIR / f"{trial_id}.labels.json", payload)
                self.send_json({"ok": True, "progress": progress_for(trial_id, frame_count)})
                return
            if path == "/api/finalize":
                result = finalize_all()
                self.send_json(result)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)


def serve(host: str, port: int, open_browser: bool) -> None:
    if not HTML_PATH.exists():
        raise FileNotFoundError(HTML_PATH)
    server = LabelServer((host, port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n라벨링 화면: {url}")
    print("창을 닫은 뒤 이 터미널에서 Ctrl+C를 누르면 종료됩니다.\n")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sub12-14 WORK/MOVE/IDLE manual labeler")
    parser.add_argument("command", choices=["prepare", "serve", "prepare-serve", "finalize"], nargs="?", default="prepare-serve")
    parser.add_argument("--force", action="store_true", help="MCAP 전처리 캐시를 다시 만듭니다.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.command in ("prepare", "prepare-serve"):
        prepare_all(force=args.force)
    if args.command == "finalize":
        prepare_all(force=False)
        print(json.dumps(finalize_all(), ensure_ascii=False, indent=2))
    if args.command in ("serve", "prepare-serve"):
        if not (OUT_ROOT / "manifest.json").exists():
            prepare_all(force=False)
        serve(args.host, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
