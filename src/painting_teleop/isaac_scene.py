"""Isaac Sim 5.1 adapter. Import only after SimulationApp has started."""

from pathlib import Path
import numpy as np
from .geometry import JOINT_NAMES, ROLLER_LINK, RobotGeometry, prepare_urdf


class TimelineStopped(Exception):
    """Native Stop invalidates physics handles; this trial must finish."""


class IsaacScene:
    def __init__(self, config, root):
        import omni.kit.commands
        import omni.usd
        import carb
        from pxr import Usd, UsdPhysics, UsdLux, PhysxSchema, Gf
        from isaacsim.core.api import World
        from isaacsim.core.api.materials import PhysicsMaterial
        from isaacsim.core.api.objects import FixedCuboid
        from isaacsim.core.prims import SingleArticulation, RigidPrim
        from isaacsim.core.utils.extensions import enable_extension
        from isaacsim.core.utils.types import ArticulationAction

        self.config = config
        # Native custom cylinder/cone geometries cannot report contact impulses.
        # Match Isaac Lab's PhysX setup before importing the roller cylinder.
        settings = carb.settings.get_settings()
        settings.set_bool("/physics/collisionCylinderCustomGeometry", False)
        settings.set_bool("/physics/collisionConeCustomGeometry", False)
        self.physics_dt = 1 / config["physics_hz"]
        self.action_type = ArticulationAction
        self.geometry = RobotGeometry(Path(root) / config["robot_urdf"])
        self.world = World(
            physics_dt=self.physics_dt,
            rendering_dt=1 / 60,
            stage_units_in_meters=1.0,
            backend="numpy",
        )
        enable_extension("isaacsim.asset.importer.urdf")
        from isaacsim.asset.importer.urdf import _urdf

        imported = prepare_urdf(
            Path(root) / config["robot_urdf"],
            Path(root) / ".cache/painting/robot_paint.urdf",
        )
        options = _urdf.ImportConfig()
        options.merge_fixed_joints = False
        options.fix_base = True
        options.convex_decomp = False
        options.make_default_prim = False
        options.self_collision = False
        options.distance_scale = 1.0
        options.density = 0.0
        ok, robot_path = omni.kit.commands.execute(
            "URDFParseAndImportFile", urdf_path=str(imported), import_config=options
        )
        if not ok:
            raise RuntimeError("URDF import failed; see Isaac Sim importer log")
        stage = omni.usd.get_context().get_stage()
        subtree = list(Usd.PrimRange(stage.GetPrimAtPath(robot_path)))
        roots = [p for p in subtree if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        rollers = [
            p
            for p in subtree
            if p.GetName() == ROLLER_LINK and p.HasAPI(UsdPhysics.RigidBodyAPI)
        ]
        if len(roots) != 1 or len(rollers) != 1:
            raise RuntimeError(
                f"Expected one articulation and roller body, got {len(roots)}, {len(rollers)}"
            )
        for prim in subtree:
            if prim.IsA(UsdPhysics.RevoluteJoint):
                drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
                drive.CreateMaxForceAttr(config["joint_max_force"])
        self.robot = self.world.scene.add(
            SingleArticulation(prim_path=str(roots[0].GetPath()), name="painting_rb10")
        )

        material = PhysicsMaterial(
            "/World/ContactMaterial",
            static_friction=0.1,
            dynamic_friction=0.1,
            restitution=0.0,
        )
        compliance = PhysxSchema.PhysxMaterialAPI.Apply(
            stage.GetPrimAtPath("/World/ContactMaterial")
        )
        compliance.CreateCompliantContactStiffnessAttr().Set(
            config["contact_stiffness_N_m"]
        )
        compliance.CreateCompliantContactDampingAttr().Set(
            config["contact_damping_N_s_m"]
        )
        compliance.CreateRestitutionCombineModeAttr().Set("max")
        compliance.CreateDampingCombineModeAttr().Set("max")
        wall = FixedCuboid(
            "/World/Wall",
            name="wall",
            size=1.0,
            position=np.array(
                [config["wall_x_m"] + 0.025, *config["wall_center_yz_m"]]
            ),
            scale=np.array([0.05, *config["wall_size_yz_m"]]),
            color=np.array([0.82, 0.84, 0.88]),
            physics_material=material,
        )
        self.world.scene.add(wall)
        # The base is at z=0; the supplied table extends down to -0.823 m.
        self.world.scene.add(
            FixedCuboid(
                "/World/Floor",
                name="floor",
                size=1.0,
                position=np.array([0.0, 0.0, -0.85]),
                scale=np.array([3.0, 3.0, 0.05]),
                color=np.array([0.22, 0.24, 0.27]),
            )
        )
        light = UsdLux.DomeLight.Define(stage, "/World/Light")
        light.CreateIntensityAttr(1000.0)
        light.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
        self.contacts = self.world.scene.add(
            RigidPrim(
                prim_paths_expr=str(rollers[0].GetPath()),
                name="roller_wall_contact",
                reset_xform_properties=False,
                track_contact_forces=True,
                contact_filter_prim_paths_expr=["/World/Wall"],
            )
        )
        self.world.reset()
        self.indices = np.array(
            [self.robot.get_dof_index(name) for name in JOINT_NAMES], dtype=int
        )
        if len(set(self.indices)) != 6 or np.any(self.indices < 0):
            raise RuntimeError(f"Unexpected robot DOFs: {self.robot.dof_names}")
        self.robot.get_articulation_controller().set_gains(
            kps=np.full(self.robot.num_dof, config["joint_stiffness"]),
            kds=np.full(self.robot.num_dof, config["joint_damping"]),
        )
        q = np.deg2rad(config["initial_joints_deg"])
        # Teleport only during initialization; all trial movement uses joint drives.
        self.robot.set_joint_positions(q, joint_indices=self.indices)
        self.robot.set_joint_velocities(np.zeros(6), joint_indices=self.indices)
        self.apply(q)
        for _ in range(config["physics_hz"]):
            self.world.step(render=False)
        measured = self.joints()
        if np.max(np.abs(measured - q)) > 0.1:
            raise RuntimeError(
                "Initial posture did not settle; inspect gains, assets and gravity"
            )
        tcp = next((p for p in subtree if p.GetName() == "tcp"), None)
        if tcp is None:
            raise RuntimeError("Imported TCP frame is missing")
        # Check the imported root/frame convention against the same URDF kinematics.
        from isaacsim.core.prims import SingleXFormPrim

        self.tcp = SingleXFormPrim(str(tcp.GetPath()), reset_xform_properties=False)
        world_position, _ = self.tcp.get_world_pose()
        if np.linalg.norm(world_position - self.geometry.fk(measured)[:3, 3]) > 0.003:
            raise RuntimeError(
                "USD and link0 FK disagree by more than 3 mm; check root transform"
            )
        from isaacsim.core.utils.viewports import set_camera_view

        set_camera_view(
            eye=np.array([-1.0, -1.7, 1.25]), target=np.array([0.35, -0.1, 0.65])
        )

    def joints(self):
        q = np.asarray(
            self.robot.get_joint_positions(joint_indices=self.indices), float
        )
        if q.shape != (6,) or not np.isfinite(q).all():
            raise RuntimeError("Invalid measured joints")
        return q

    def apply(self, q):
        self.robot.apply_action(
            self.action_type(joint_positions=q, joint_indices=self.indices)
        )

    def step(self, render=False):
        if self.world.is_stopped():
            raise TimelineStopped()
        self.world.step(render=False)
        if self.world.is_stopped():
            raise TimelineStopped()
        value = self.contacts.get_contact_force_matrix(dt=self.physics_dt)
        if value is None:
            raise RuntimeError("PhysX contact view returned no data")
        value = np.asarray(value, float)
        if value.shape != (1, 1, 3) or not np.isfinite(value).all():
            raise RuntimeError(f"Invalid roller-wall contact matrix: {value.shape}")
        reaction = value[0, 0].copy()
        if render:
            # world.step(render=True) would advance one rendering interval, not
            # necessarily one physics interval. Render only after sampling.
            self.world.render()
            if self.world.is_stopped():
                raise TimelineStopped()
        return reaction


class OperatorPanel:
    def __init__(self, condition, headless=False):
        self.task = "UNMARKED"
        self.keyboard_clutch = False
        self.stop = False
        self.label = None
        self.subscription = None
        if headless:
            return
        import omni.ui as ui
        import carb.input
        import omni.appwindow

        self.input_api = carb.input.acquire_input_interface()
        self.keyboard = omni.appwindow.get_default_app_window().get_keyboard()
        self.subscription = self.input_api.subscribe_to_keyboard_events(
            self.keyboard, self.on_key
        )
        self.window = ui.Window("Painting Teleoperation", width=430, height=285)
        with self.window.frame:
            with ui.VStack(spacing=6):
                ui.Label(f"Condition: {condition} | B / hold Space: clutch")
                ui.Label("1 Free | 2 Approach | 3 Painting | 4 Retract")
                with ui.HStack():
                    for task in ("FREE", "APPROACH", "PAINTING", "RETRACT"):
                        ui.Button(
                            task, clicked_fn=lambda t=task: setattr(self, "task", t)
                        )
                self.label = ui.Label("Waiting for input...", word_wrap=True)
                ui.Button(
                    "End trial / Esc", clicked_fn=lambda: setattr(self, "stop", True)
                )

    def on_key(self, event):
        import carb.input

        key = event.input.name
        pressed = event.type in (
            carb.input.KeyboardEventType.KEY_PRESS,
            carb.input.KeyboardEventType.KEY_REPEAT,
        )
        if key == "SPACE":
            self.keyboard_clutch = pressed
        if pressed:
            if key in ("KEY_1", "KEY_2", "KEY_3", "KEY_4"):
                self.task = ("FREE", "APPROACH", "PAINTING", "RETRACT")[
                    int(key[-1]) - 1
                ]
            elif key == "ESCAPE":
                self.stop = True
        return True

    def update(self, t, force, gap, decision, probability, enabled):
        if self.label:
            self.label.text = (
                f"{t:.1f} s | Task: {self.task}\n"
                f"Force {force:.2f} N | Gap {gap*1000:.2f} mm\n"
                f'Input {"ACTIVE" if enabled else "HOLD"} | {decision.mode}\n'
                f"Authority {decision.authority:.2f} | LSTM paint {probability[2]:.2f}"
            )

    def close(self):
        if self.subscription is not None:
            self.input_api.unsubscribe_to_keyboard_events(
                self.keyboard, self.subscription
            )
