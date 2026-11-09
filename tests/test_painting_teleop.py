import json
import sys
import unittest
import tempfile
import socket
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from painting_teleop.controller import Controller, Observation, Parameters
from painting_teleop.input import InputBuffer, UDPInput, packet, parse_haply
from painting_teleop.geometry import RobotGeometry, prepare_urdf
from painting_teleop.metrics import summarize
from painting_teleop.lstm import PhaseLSTM
from painting_teleop.session import ControlSession, ReplayInput, TrialLogger


class ControllerTests(unittest.TestCase):
    def obs(self, **kwargs):
        values = dict(
            dt=1 / 30,
            human=0.0,
            force=10.0,
            gap=0.0,
            probabilities=[0, 0, 1, 0],
            enabled=True,
        )
        values.update(kwargs)
        return Observation(**values)

    def test_outward_input_is_not_opposed_with_stale_painting(self):
        c = Controller()
        for _ in range(15):
            c.step(self.obs())
        r = c.step(self.obs(human=-0.005, force=5.0))
        self.assertLessEqual(r.command, -0.005)

    def test_contact_loss_without_withdrawal_recovers(self):
        c = Controller()
        c.step(self.obs())
        r = c.step(self.obs(force=0.0, gap=0.002))
        self.assertEqual(r.mode, "recover")
        self.assertGreater(r.command, 0.0)

    def test_release_stays_released_until_inward_request_even_after_pause(self):
        c = Controller()
        c.step(self.obs())
        c.step(self.obs(human=-0.01, force=4.0))
        c.step(self.obs(human=-0.01, force=0.0, gap=0.003))
        c.step(self.obs(enabled=False, force=0.0, gap=0.003))
        r = c.step(self.obs(force=0.0, gap=0.003))
        self.assertEqual(r.command, 0.0)
        r = c.step(
            self.obs(human=0.002, force=0.0, gap=0.003, probabilities=[0, 0, 0, 1])
        )
        self.assertEqual(r.mode, "recover")
        self.assertGreaterEqual(r.command, 0.002)

    def test_release_intent_survives_neutral_input_while_contact_decays(self):
        c = Controller()
        c.step(self.obs())
        c.step(self.obs(human=-0.01, force=5.0))
        self.assertLessEqual(c.step(self.obs(human=0.0, force=1.1)).command, 0.0)
        r = c.step(self.obs(human=0.0, force=0.0, gap=0.001))
        self.assertEqual(r.mode, "released")
        self.assertEqual(r.command, 0.0)

    def test_no_prior_contact_does_not_autonomously_seek_wall(self):
        r = Controller().step(self.obs(force=0.0, gap=0.003))
        self.assertEqual(r.command, 0.0)

    def test_recovery_stops_at_time_and_distance_bounds(self):
        c = Controller(Parameters(recovery_timeout_s=0.05))
        c.step(self.obs())
        for _ in range(4):
            r = c.step(self.obs(force=0.0, gap=0.002))
        self.assertEqual(r.command, 0.0)
        c = Controller()
        c.step(self.obs())
        self.assertEqual(c.step(self.obs(force=0.0, gap=0.1)).command, 0.0)

    def test_disabled_and_invalid_observations_produce_no_motion(self):
        c = Controller()
        self.assertEqual(c.step(self.obs(enabled=False, human=0.02)).command, 0.0)
        for key in ["human", "force", "gap", "dt"]:
            with self.assertRaises(ValueError):
                c.step(self.obs(**{key: float("nan")}))

    def test_manual_and_probability_conditions_are_distinct_baselines(self):
        self.assertEqual(
            Controller(condition="manual").step(self.obs(human=0.01)).command, 0.01
        )
        c = Controller(condition="probability")
        c.step(self.obs())
        self.assertEqual(c.step(self.obs(force=0.0, gap=0.002)).command, 0.0)


class InputTests(unittest.TestCase):
    def test_bridge_only_requests_zero_force_and_full_state(self):
        from painting_teleop.haply_bridge import stream_request

        d = stream_request("arm", "wireless_verse_grip", "grip", "values")
        self.assertEqual(
            d["inverse3"][0]["commands"]["set_cursor_force"]["values"],
            dict(x=0.0, y=0.0, z=0.0),
        )
        self.assertIn("force_render_full_state", d["session"])

    def test_old_udp_backlog_cannot_reactivate_after_pause(self):
        receiver = UDPInput(port=0, scale=1.0, axis_matrix=np.eye(3))
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            d = json.loads(packet("s", 0, [0, 0, 0], True))
            d["sent_at"] = time.monotonic() - 10
            sender.sendto(json.dumps(d).encode(), receiver.socket.getsockname())
            import select

            self.assertTrue(select.select([receiver.socket], [], [], 1.0)[0])
            self.assertFalse(receiver.sample(time.monotonic(), 1 / 30)[1])
            self.assertIsNone(receiver.buffer.latest)
        finally:
            sender.close()
            receiver.close()

    def test_clutch_edge_duplicates_timeout_and_reconnect_do_not_jump(self):
        b = InputBuffer(timeout_s=0.15, scale=1.0, axis_matrix=np.eye(3))
        self.assertTrue(b.ingest(packet("one", 0, [0, 0, 0], True), 0.0))
        np.testing.assert_equal(b.sample(0.01, 1 / 30)[0], [0, 0, 0])
        b.ingest(packet("one", 1, [0.001, 0, 0], True), 0.02)
        np.testing.assert_allclose(b.sample(0.03, 1 / 30)[0], [0.03, 0, 0])
        self.assertFalse(b.ingest(packet("one", 1, [0.1, 0, 0], True), 0.04))
        np.testing.assert_equal(b.sample(0.05, 1 / 30)[0], [0, 0, 0])
        self.assertFalse(b.sample(0.3, 1 / 30)[1])
        b.ingest(packet("two", 0, [0.2, 0, 0], True), 0.31)
        np.testing.assert_equal(b.sample(0.32, 1 / 30)[0], [0, 0, 0])

    def test_malformed_or_invalid_device_data_is_rejected(self):
        b = InputBuffer()
        self.assertFalse(b.ingest(b"not json", 0.0))
        self.assertFalse(b.ingest(packet("s", 0, [float("nan"), 0, 0], True), 0.0))
        state = {
            "inverse3": [
                {
                    "device_id": "i",
                    "state": {"cursor_position": {"x": 0.0, "y": 0.0, "z": 0.0}},
                    "status": {"ready": False},
                }
            ]
        }
        self.assertIsNone(parse_haply(state)[0])

    def test_haply_wireless_button_b_and_position(self):
        state = {
            "inverse3": [
                {
                    "device_id": "i",
                    "state": {"cursor_position": {"x": 0.1, "y": 0.2, "z": 0.3}},
                    "status": {"ready": True},
                }
            ],
            "wireless_verse_grip": [
                {
                    "device_id": "g",
                    "state": {"buttons": {"a": False, "b": True, "c": False}},
                    "status": {"ready": True, "connected": True, "awake": True},
                }
            ],
        }
        pos, clutch, ids = parse_haply(state)
        np.testing.assert_equal(pos, [0.1, 0.2, 0.3])
        self.assertTrue(clutch)
        self.assertEqual(ids, ("i", "wireless_verse_grip", "g"))


class GeometryAndModelTests(unittest.TestCase):
    def test_analytic_jacobian_matches_measured_fk_perturbations(self):
        from painting_teleop.geometry import rotvec

        config = json.loads((ROOT / "simulation/config/painting.json").read_text())
        g = RobotGeometry(ROOT / config["robot_urdf"])
        for offset in (0.0, 0.1, -0.1):
            q = np.deg2rad(config["initial_joints_deg"]) + offset
            T, J = g.tcp_jacobian(q)
            numerical = np.zeros((6, 6))
            for j in range(6):
                delta = np.zeros(6)
                delta[j] = 1e-5
                A = g.fk(q + delta)
                numerical[:, j] = np.r_[
                    (A[:3, 3] - T[:3, 3]) / 1e-5,
                    0.3 * rotvec(A[:3, :3] @ T[:3, :3].T) / 1e-5,
                ]
            np.testing.assert_allclose(J, numerical, atol=5e-6)

    def test_rendering_does_not_advance_an_extra_physics_step(self):
        from painting_teleop.isaac_scene import IsaacScene

        class World:
            elapsed = 0.0

            def is_stopped(self):
                return False

            def step(self, render):
                self.elapsed += (2 if render else 1) / 120

            def render(self):
                pass

        class Contact:
            def get_contact_force_matrix(self, dt):
                return np.array([[[-3.0, 0.0, 0.0]]])

        scene = IsaacScene.__new__(IsaacScene)
        scene.world = World()
        scene.contacts = Contact()
        scene.physics_dt = 1 / 120
        for i in range(4):
            scene.step(render=i % 2 == 0)
        self.assertAlmostEqual(scene.world.elapsed, 1 / 30)

    def test_native_stop_prevents_physics_and_contact_access(self):
        from painting_teleop.isaac_scene import IsaacScene, TimelineStopped

        class World:
            def is_stopped(self):
                return True

            def step(self, render):
                raise AssertionError("Stepped invalid physics")

        class Contact:
            def get_contact_force_matrix(self, dt):
                raise AssertionError("Read invalid physics")

        scene = IsaacScene.__new__(IsaacScene)
        scene.world = World()
        scene.contacts = Contact()
        scene.physics_dt = 1 / 120
        with self.assertRaises(TimelineStopped):
            scene.step(render=True)

    def test_force_sign_and_generated_asset_coordinates(self):
        source = (
            ROOT
            / "issac sim_ws/all_models_with_testpiece_and_images/rb10_base_description/urdf/robot_paint.urdf"
        )
        g = RobotGeometry(source)
        q = np.deg2rad([0.03, -53.53, 138.92, -93.35, 89.81, 0.0])
        self.assertLess(g.training_force(q, [-10, 0, 0])[2], -9.9)
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory() as td:
            out = prepare_urdf(source, Path(td) / "robot.urdf")
            tree = ET.parse(out)
            self.assertEqual(
                tree.find("joint[@name='support_to_rb10']/origin").get("rpy"), "0 0 0"
            )
            self.assertTrue(
                all(Path(e.get("filename")).is_file() for e in tree.findall(".//mesh"))
            )

    def test_ik_returns_to_known_tcp_and_roller_axis(self):
        g = RobotGeometry(
            ROOT
            / "issac sim_ws/all_models_with_testpiece_and_images/rb10_base_description/urdf/robot_paint.urdf"
        )
        q = np.deg2rad([0.03, -53.53, 138.92, -93.35, 89.81, 0.0])
        T = g.fk(q)
        self.assertGreater((T[:3, :3] @ np.array([0, -1, 0]))[0], 0.99)
        solved, error = g.ik(q + 0.005, T[:3, 3] + [0, 0.005, 0], T[:3, :3])
        self.assertLess(error, 0.001)
        self.assertTrue(np.isfinite(solved).all())

    def test_checkpoint_matches_saved_torch_reference(self):
        ref = np.load(ROOT / "tests/fixtures/lstm_reference.npz")
        model = PhaseLSTM(ROOT / "simulation/models/phase_lstm.npz")
        actual = np.array([model.step(x) for x in ref["features"]])
        np.testing.assert_allclose(actual, ref["probabilities"], atol=3e-6, rtol=2e-5)
        model.reset()
        np.testing.assert_allclose(model.step(ref["features"][0]), actual[0])


class MetricTests(unittest.TestCase):
    def test_evaluation_uses_task_marker_not_predicted_painting(self):
        rows = [
            dict(
                dt_s=0.1,
                task="PAINTING",
                force_N=10.0,
                human_normal_m_s=0.0,
                command_normal_m_s=0.0,
                gap_m=0.0,
                enabled=True,
                fault="",
                y_m=0.0,
                z_m=0.5,
            ),
            dict(
                dt_s=0.1,
                task="RETRACT",
                force_N=0.0,
                human_normal_m_s=-0.01,
                command_normal_m_s=0.0,
                gap_m=0.01,
                enabled=True,
                fault="",
                y_m=0.0,
                z_m=0.5,
            ),
        ]
        m = summarize(rows, 10.0)
        self.assertAlmostEqual(m["painting_duration_s"], 0.1)
        self.assertEqual(m["painting_force_rmse_N"], 0.0)
        self.assertAlmostEqual(m["withdrawal_interference_mm"], 1.0)

    def test_unmarked_trials_do_not_claim_painting_performance(self):
        self.assertIsNone(summarize([], 10.0)["painting_force_rmse_N"])

    def test_warmup_and_faults_count_as_disabled_and_contact_path_requires_contact(
        self,
    ):
        rows = [
            dict(
                dt_s=0.1,
                task="PAINTING",
                force_N=10.0,
                human_normal_m_s=0.0,
                command_normal_m_s=0.0,
                gap_m=0.0,
                enabled=True,
                feature_valid=False,
                fault="",
                y_m=0.0,
                z_m=0.5,
            ),
            dict(
                dt_s=0.1,
                task="PAINTING",
                force_N=10.0,
                human_normal_m_s=0.0,
                command_normal_m_s=0.0,
                gap_m=0.0,
                enabled=True,
                feature_valid=True,
                fault="",
                y_m=0.0,
                z_m=0.51,
            ),
            dict(
                dt_s=0.1,
                task="PAINTING",
                force_N=0.0,
                human_normal_m_s=0.0,
                command_normal_m_s=0.0,
                gap_m=0.01,
                enabled=True,
                feature_valid=True,
                fault="tracking_limit",
                y_m=0.0,
                z_m=0.52,
            ),
        ]
        m = summarize(rows)
        self.assertAlmostEqual(m["painting_disabled_pct"], 200 / 3)
        self.assertAlmostEqual(m["painting_contact_path_m"], 0.01)


class SessionTests(unittest.TestCase):
    def test_pause_renders_without_advancing_and_end_button_exits(self):
        from painting_teleop.runtime import wait_until_playing
        from types import SimpleNamespace

        panel = SimpleNamespace(stop=False, keyboard_clutch=True)
        app = SimpleNamespace(is_running=lambda: True)

        class World:
            playing = False

            def is_playing(self):
                return self.playing

            def is_stopped(self):
                return False

            def render(self):
                self.playing = True

        world = World()
        self.assertIsNone(wait_until_playing(world, app, panel))
        self.assertFalse(panel.keyboard_clutch)
        world.playing = False
        world.render = lambda: setattr(panel, "stop", True)
        self.assertEqual(wait_until_playing(world, app, panel), "operator_stop")

    def test_log_and_replay_preserve_input_and_independent_labels(self):
        from painting_teleop.session import sample_row

        config = json.loads((ROOT / "simulation/config/painting.json").read_text())
        session = ControlSession(config, ROOT)
        with tempfile.TemporaryDirectory() as td:
            log = TrialLogger(
                Path(td) / "trial", dict(config=config, condition="manual")
            )
            for i in range(20):
                command, d, p, u, valid, h = session.step(
                    i / 30, [0.2, 0, 0.7], [0, 0, 0], [0.01, 0.02, 0], 0.0, 0.04, True
                )
                log.write(
                    sample_row(
                        i / 30,
                        1 / 30,
                        i / 30,
                        "RETRACT",
                        0.0,
                        0.04,
                        [0.2, 0, 0.7],
                        h,
                        command,
                        d,
                        p,
                        u,
                        True,
                        valid,
                    )
                )
            log.close()
            replay = ReplayInput(log.directory / "samples.csv")
            v, enabled, task = replay.sample(19 / 30, 1 / 30)
            np.testing.assert_allclose(v, [0.01, 0.02, 0])
            self.assertTrue(enabled)
            self.assertEqual(task, "RETRACT")
            self.assertIsNone(
                json.loads((log.directory / "summary.json").read_text())[
                    "painting_force_rmse_N"
                ]
            )

    def test_warmup_and_clutch_disable_hold_all_axes(self):
        config = json.loads((ROOT / "simulation/config/painting.json").read_text())
        s = ControlSession(config, ROOT)
        for i in range(16):
            out = s.step(
                i / 30, [0.2, 0, 0.7], [0, 0, 0], [0.01, 0.01, 0.01], 0.0, 0.04, True
            )
            if i < 15:
                np.testing.assert_equal(out[0], [0, 0, 0])
        self.assertTrue(out[4])
        np.testing.assert_equal(
            s.step(
                16 / 30, [0.2, 0, 0.7], [0, 0, 0], [0.01, 0.01, 0.01], 0.0, 0.04, False
            )[0],
            [0, 0, 0],
        )


if __name__ == "__main__":
    unittest.main()
