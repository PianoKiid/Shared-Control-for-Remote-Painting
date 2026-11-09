"""Local protocol integration; no Haply or robot hardware is accessed."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from painting_teleop.input import UDPInput
from painting_teleop.haply_bridge import forward_connection


@unittest.skipUnless(
    importlib.util.find_spec("websockets"),
    "Install simulation/requirements-haply.txt for WebSocket integration",
)
class HaplyTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_to_udp_mapping_clutch_and_disconnect(self):
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed

        requests = []

        async def service(ws):
            i = 0
            try:
                async for message in ws:
                    requests.append(json.loads(message))
                    await ws.send(
                        json.dumps(
                            {
                                "inverse3": [
                                    {
                                        "device_id": "fake-arm",
                                        "status": {"ready": True},
                                        "state": {
                                            "cursor_position": dict(
                                                x=0.0, y=i * 0.0001, z=0.0
                                            )
                                        },
                                    }
                                ],
                                "wireless_verse_grip": [
                                    {
                                        "device_id": "fake-grip",
                                        "status": dict(
                                            ready=True, connected=True, awake=True
                                        ),
                                        "state": {"buttons": {"b": True}},
                                    }
                                ],
                            }
                        )
                    )
                    i += 1
                    await asyncio.sleep(0.01)
            except ConnectionClosed:
                pass

        receiver = UDPInput(port=0, scale=1.0)
        velocities = []
        try:
            async with serve(service, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f"ws://127.0.0.1:{port}") as ws:
                    forwarding = asyncio.create_task(
                        forward_connection(
                            ws, receiver.socket.getsockname(), stop_after_s=0.18
                        )
                    )
                    while not forwarding.done():
                        await asyncio.sleep(0.02)
                        v, _ = receiver.sample(time.monotonic(), 0.02)
                        velocities.append(v)
                    await forwarding
            self.assertGreater(max(v[0] for v in velocities), 0.0)
            self.assertTrue(all(np.allclose(v[1:], 0.0) for v in velocities))
            commands = [
                r["inverse3"][0]["commands"]["set_cursor_force"]["values"]
                for r in requests
                if "inverse3" in r
            ]
            self.assertTrue(commands)
            self.assertTrue(all(v == dict(x=0.0, y=0.0, z=0.0) for v in commands))
            await asyncio.sleep(0.17)
            self.assertFalse(receiver.sample(time.monotonic(), 0.02)[1])
        finally:
            receiver.close()
