"""Haply Inverse Service 3.x -> localhost UDP; input streaming at zero force."""

import asyncio
import json
import socket
import time
import uuid

from .input import packet, parse_haply


def stream_request(device_id=None, grip_kind=None, grip_id=None, force_key="values"):
    if force_key not in ("values", "vector"):
        raise ValueError("force_key must match the installed Inverse Service API")
    request = {"session": {"force_render_full_state": {}}}
    if device_id is not None:
        request["inverse3"] = [
            {
                "device_id": device_id,
                "commands": {
                    "set_cursor_force": {force_key: dict(x=0.0, y=0.0, z=0.0)}
                },
            }
        ]
    if grip_kind and grip_id:
        request[grip_kind] = [
            {"device_id": grip_id, "commands": {"probe_orientation": {}}}
        ]
    return request


async def forward_connection(
    ws, destination, device_id=None, grip_id=None, force_key="values", stop_after_s=None
):
    """A new session ID re-anchors the simulator after every reconnection."""
    session = uuid.uuid4().hex
    seq = 0
    ids = (device_id, None, grip_id)
    started = time.monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        await ws.send(json.dumps(stream_request(force_key=force_key)))
        try:
            while stop_after_s is None or time.monotonic() - started < stop_after_s:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Expected Inverse Service 3.x object")
                position, clutch, found = parse_haply(data, ids[0], ids[2])
                ids = tuple(
                    old if old is not None else new for old, new in zip(ids, found)
                )
                if position is not None:
                    udp.sendto(packet(session, seq, position, clutch), destination)
                    seq += 1
                await ws.send(json.dumps(stream_request(*ids, force_key)))
                if ids[0] is None:
                    await asyncio.sleep(0.05)
        finally:
            # The last outgoing device command, like every earlier one, is zero.
            try:
                await ws.send(json.dumps(stream_request(*ids, force_key)))
            except Exception:
                pass


async def run_bridge(args):
    try:
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed
    except ImportError as exc:
        raise RuntimeError(
            "Install bridge dependencies: python -m pip install -r simulation/requirements-haply.txt"
        ) from exc
    print(
        f"Haply {args.url} -> 127.0.0.1:{args.port}; wireless B / wired button clutch; zero force",
        flush=True,
    )
    while True:
        try:
            async with connect(args.url, max_queue=1, open_timeout=3.0) as ws:
                print(
                    "Connected. First valid Inverse3 and grip are pinned for this connection.",
                    flush=True,
                )
                await forward_connection(
                    ws,
                    ("127.0.0.1", args.port),
                    args.device_id,
                    args.grip_id,
                    args.force_key,
                )
        except (
            OSError,
            TimeoutError,
            ConnectionClosed,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            print(f"Input disconnected: {exc}. Retrying in 1 s.", flush=True)
            await asyncio.sleep(1.0)
