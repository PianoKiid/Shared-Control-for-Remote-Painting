"""Haply 3.x JSON and localhost input transport; positions are metres."""

import json
import math
import socket
import time
import numpy as np


def packet(session, seq, position, clutch):
    return json.dumps(
        dict(
            schema=1,
            session=session,
            seq=seq,
            position_m=list(position),
            clutch=bool(clutch),
            sent_at=time.monotonic(),
        )
    ).encode()


def parse_haply(data, device_id=None, grip_id=None):
    devices = data.get("inverse3", [])
    device = next(
        (d for d in devices if device_id is None or d.get("device_id") == device_id),
        None,
    )
    grip = None
    kind = None
    for k in ("wireless_verse_grip", "verse_grip"):
        grip = next(
            (
                d
                for d in data.get(k, [])
                if grip_id is None or d.get("device_id") == grip_id
            ),
            None,
        )
        if grip is not None:
            kind = k
            break
    ids = (
        device.get("device_id") if device else None,
        kind,
        grip.get("device_id") if grip else None,
    )
    if device is None or not device.get("status", {}).get("ready", False):
        return None, False, ids
    try:
        pos = np.array([device["state"]["cursor_position"][a] for a in "xyz"], float)
        if not np.isfinite(pos).all():
            return None, False, ids
    except (KeyError, TypeError, ValueError):
        return None, False, ids
    clutch = False
    if grip is not None:
        s = grip.get("status", {})
        state = grip.get("state", {})
        ready = (
            s.get("ready", False) and s.get("connected", True) and s.get("awake", True)
        )
        clutch = bool(
            ready
            and (
                state.get("buttons", {}).get("b", False)
                if kind == "wireless_verse_grip"
                else state.get("button", False)
            )
        )
    return pos, clutch, ids


class InputBuffer:
    def __init__(self, timeout_s=0.15, scale=9.0, axis_matrix=None):
        self.timeout = timeout_s
        self.scale = scale
        self.matrix = np.array(
            [[0, 1, 0], [-1, 0, 0], [0, 0, 1]] if axis_matrix is None else axis_matrix,
            float,
        )
        if (
            self.matrix.shape != (3, 3)
            or not np.isfinite(self.matrix).all()
            or not math.isfinite(scale)
            or scale <= 0
            or timeout_s <= 0
        ):
            raise ValueError("Invalid input mapping")
        self.session = None
        self.seq = -1
        self.latest = None
        self.received = -math.inf
        self.anchor = None
        self.active = False
        self.reset_pending = True
        self.retired = set()

    def ingest(self, payload, now=None):
        now = time.monotonic() if now is None else now
        try:
            d = json.loads(payload)
            pos = np.asarray(d["position_m"], float)
            if (
                d["schema"] != 1
                or type(d["seq"]) is not int
                or d["seq"] < 0
                or type(d["clutch"]) is not bool
                or not isinstance(d["session"], str)
                or not d["session"]
                or len(d["session"]) > 80
                or pos.shape != (3,)
                or not np.isfinite(pos).all()
            ):
                return False
            if d["session"] in self.retired:
                return False
            if d["session"] != self.session:
                if self.session is not None:
                    self.retired.add(self.session)
                self.session = d["session"]
                self.seq = -1
                self.reset_pending = True
            if d["seq"] <= self.seq:
                return False
            if (
                now - self.received > self.timeout
                or self.latest is None
                or d["clutch"] != self.latest["clutch"]
            ):
                self.reset_pending = True
            self.seq = d["seq"]
            self.latest = d
            self.received = now
            return True
        except (ValueError, KeyError, TypeError, UnicodeError):
            return False

    def sample(self, now, dt, keyboard_clutch=False):
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("Invalid sample interval")
        fresh = self.latest is not None and 0 <= now - self.received <= self.timeout
        enabled = bool(fresh and (self.latest["clutch"] or keyboard_clutch))
        if not enabled:
            self.active = False
            self.anchor = None
            return np.zeros(3), False
        pos = np.array(self.latest["position_m"])
        if not self.active or self.reset_pending or self.anchor is None:
            self.anchor = pos
            self.active = True
            self.reset_pending = False
            return np.zeros(3), True
        velocity = self.scale * (self.matrix @ (pos - self.anchor)) / dt
        self.anchor = pos
        return velocity, True


class UDPInput:
    def __init__(self, host="127.0.0.1", port=15000, **kwargs):
        self.buffer = InputBuffer(**kwargs)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host, port))
        self.socket.setblocking(False)

    def sample(self, now, dt, keyboard_clutch=False):
        for _ in range(512):
            try:
                data, _ = self.socket.recvfrom(4096)
            except BlockingIOError:
                break
            try:
                # Both processes run on the same host and share its monotonic clock.
                sent = float(json.loads(data)["sent_at"])
                if not 0 <= now - sent <= self.buffer.timeout:
                    continue
            except (ValueError, KeyError, TypeError, UnicodeError):
                continue
            self.buffer.ingest(data, sent)
        return self.buffer.sample(now, dt, keyboard_clutch)

    def close(self):
        self.socket.close()
