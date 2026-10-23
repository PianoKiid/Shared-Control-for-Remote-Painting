"""
RB10 관절 조종 창 (마우스 슬라이더 + 키보드 + 마우스로 목표점 끌기)

먼저 lab_env_setup.py 를 실행해서 실험실과 로봇을 만든 다음,
Script Editor 에 이 파일 전체를 붙여넣고 Run → ▶ Play.

조작
  마우스  : 창의 슬라이더 6개를 끌면 해당 관절이 그 각도로 움직임
  키보드  : 1~6        관절 선택 (base, shoulder, elbow, wrist1, wrist2, wrist3)
            ↑ / ↓      선택한 관절 +1° / -1°
            Shift+↑↓   +5° / -5°
            R          작업 자세(WORK_POSE)로 되돌리기
            F          목표점 따라가기 켜기/끄기
  목표점 따라가기 (Mouse target):
            켜면 롤러 중심에 주황색 공(/World/TCP_Target)이 생긴다.
            뷰포트에서 공을 클릭 → W(이동 도구) → 화살표를 마우스로 끌면
            롤러가 공을 따라온다 (역기구학 IK 로 관절각 계산).
            기본은 도구 방향 고정(벽을 향한 그대로). "Use target rotation" 을 켜면
            E(회전 도구)로 공을 돌려서 도구 방향도 바꿀 수 있다.
  ※ 관절은 ▶ Play 중에만 움직인다 (멈춘 상태에서는 목표값만 바뀜).

각도는 실제 RB10 펜던트 기준(도, °)으로 보여준다.
base 관절은 lab_env_setup.py 의 -90° 보정을 여기서도 똑같이 더해서 시뮬레이션에 넣는다.

동작 원리
  각 관절의 모터(DriveAPI) "목표 각도(targetPosition)" 값을 바꾼다.
  모터가 stiffness/damping 으로 그 각도까지 관절을 끌고 간다.
  (Isaac Sim 창 글꼴이 한글을 못 보여줘서 창·출력 글자는 영어로 둔다)
"""
import builtins
import math
import numpy as np
import carb
import carb.input
import omni.appwindow
import omni.kit.app
import omni.ui as ui
import omni.usd
from pxr import Gf, Usd, UsdGeom, UsdPhysics

# =============================================================================
# 설정
# =============================================================================
BASE_OFFSET_DEG = -90.0          # lab_env_setup.py 와 같은 값이어야 함
STEP_DEG, BIG_STEP_DEG = 1.0, 5.0
LIMIT_DEG = 180.0                # URDF limit ±3.14 rad

JOINTS = ["base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"]
WORK_POSE_DEG = {                # 펜던트 값 (doc: phase4_session4_environment.md)
    "base": 0.03, "shoulder": -53.53, "elbow": 138.92,
    "wrist1": -93.35, "wrist2": 89.81, "wrist3": 0.0,
}

# =============================================================================
# 이전에 띄운 조종 창이 있으면 정리 (Run 을 여러 번 눌러도 창이 겹치지 않게)
# =============================================================================
_old = getattr(builtins, "_rb10_teleop", None)
if _old:
    try:
        _old["inp"].unsubscribe_to_keyboard_events(_old["kb"], _old["sub"])
    except Exception:
        pass
    try:
        _old["update_sub"].unsubscribe()
    except Exception:
        pass
    try:
        _old["window"].destroy()
    except Exception:
        pass
    builtins._rb10_teleop = None

# =============================================================================
# 관절 모터 찾기
# =============================================================================
stage = omni.usd.get_context().get_stage()
drives = {}
for p in stage.Traverse():
    if p.IsA(UsdPhysics.RevoluteJoint) and p.GetName() in JOINTS:
        drives[p.GetName()] = UsdPhysics.DriveAPI.Apply(p, "angular")   # 이미 있으면 그대로 사용

if len(drives) != 6:
    raise RuntimeError(f"Found {len(drives)} joints: {list(drives)} - run lab_env_setup.py first")
print(f"[OK] joints: {list(drives)}")


def _offset(name):
    return BASE_OFFSET_DEG if name == "base" else 0.0


def _current_pendant_deg(name):
    """지금 모터 목표값을 펜던트 각도로 (base 는 보정 빼기)."""
    v = drives[name].GetTargetPositionAttr().Get()
    return (float(v) if v is not None else 0.0) - _offset(name)


def _set_target(name, pendant_deg):
    """펜던트 각도 → 시뮬레이션 모터 목표값 (base 는 보정 더하기)."""
    pendant_deg = max(-LIMIT_DEG, min(LIMIT_DEG, pendant_deg))
    drives[name].GetTargetPositionAttr().Set(pendant_deg + _offset(name))


# =============================================================================
# 순기구학(FK) / 역기구학(IK) — robot_paint.urdf 수치, 펜던트 각도(도) 기준
#   world 기준 TCP 위치를 계산한다. (link0 +90° 와 base -90° 보정이 상쇄된 상태 = 보정 없는 URDF FK)
#   검증: WORK_POSE 에서 TCP = (0.174, -0.154, 0.739), 도구 방향 ≈ +X(벽).
#         벽 작업영역 전체(롤러가 벽에 닿는 거리, 50×40 cm)를 도구 방향 고정 상태로 도달 가능 (오차 < 0.01 mm)
# =============================================================================
def _rpy(r, p, y):
    cr, sr, cp, sp = math.cos(r), math.sin(r), math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _T(xyz=(0.0, 0.0, 0.0), rpy=(0.0, 0.0, 0.0)):
    M = np.eye(4)
    M[:3, :3] = _rpy(*rpy)
    M[:3, 3] = xyz
    return M


def _Rz(q):
    c, s = math.cos(q), math.sin(q)
    M = np.eye(4)
    M[:2, :2] = [[c, -s], [s, c]]
    return M


def _Ry(q):
    c, s = math.cos(q), math.sin(q)
    M = np.eye(4)
    M[0, 0], M[0, 2], M[2, 0], M[2, 2] = c, s, -s, c
    return M


_CHAIN = [  # URDF joint origin(부모 기준) + 회전축 : base, shoulder, elbow, wrist1, wrist2, wrist3
    ((0, 0, 0), _Rz), ((0, 0, 0.197), _Ry), ((0, -0.1875, 0.6127), _Ry),
    ((0, 0.1514, 0.57015), _Ry), ((0, -0.11715, 0), _Rz), ((0, 0, 0.11715), _Ry),
]
# link6 → ft_link → tcp (URDF fixed joint)
_TOOL = _T((0, 0.0147, 0), (-math.pi / 2, math.pi / 2, 0)) @ _T((0, 0, -0.13), (math.pi / 2, 0, -math.pi / 2))


def fk(q_deg):
    """펜던트 관절각(도) 6개 → TCP 4x4 행렬 (world)."""
    M = np.eye(4)
    for (xyz, rot), q in zip(_CHAIN, q_deg):
        M = M @ _T(xyz) @ rot(math.radians(q))
    return M @ _TOOL


def _rotvec(R):
    """회전행렬 → 회전벡터 (방향 오차 계산용)."""
    a = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0)))
    if a < 1e-9:
        return np.zeros(3)
    if abs(math.pi - a) < 1e-6:
        return np.sqrt(np.maximum((np.diag(R) + 1.0) / 2.0, 0.0)) * a
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return v * a / (2.0 * math.sin(a))


def ik(q_seed_deg, p_target, R_target, iters=40, damping=0.05):
    """감쇠 최소제곱(DLS) IK: TCP 를 목표 위치·방향에 맞추는 관절각(도), 위치 오차(m)."""
    q = np.radians(np.asarray(q_seed_deg, float))

    def err(qr):
        M = fk(np.degrees(qr))
        return np.concatenate([p_target - M[:3, 3], 0.3 * _rotvec(R_target @ M[:3, :3].T)])

    for _ in range(iters):
        e = err(q)
        if np.linalg.norm(e) < 1e-5:
            break
        J = np.zeros((6, 6))
        for i in range(6):
            dq = np.zeros(6)
            dq[i] = 1e-5
            J[:, i] = -(err(q + dq) - e) / 1e-5
        step = J.T @ np.linalg.solve(J @ J.T + damping ** 2 * np.eye(6), e)
        n = np.linalg.norm(step)
        if n > 0.2:
            step *= 0.2 / n
        q = np.clip(q + step, -math.radians(LIMIT_DEG), math.radians(LIMIT_DEG))
    return np.degrees(q), float(np.linalg.norm(p_target - fk(np.degrees(q))[:3, 3]))


# =============================================================================
# 목표점 (주황색 공) — 마우스로 끌면 팔 끝이 따라온다
# =============================================================================
TARGET_PATH = "/World/TCP_Target"
TARGET_RADIUS = 0.035            # 롤러(반지름 2.6 cm)보다 커서 밖으로 보이게
# 공 = 롤러 중심. TCP 기준 롤러 중심 위치 (robot_paint.urdf: eoat (0,-0.16745,0) Rx90 + 롤러 (0,-0.018,0.07675))
ROLLER_IN_TCP = np.array([0.0, -0.2442, -0.018])
follow = {"on": False, "R_lock": None, "last": None}


def _q_now():
    return [models[n].as_float for n in JOINTS]


def _target_to_tool():
    """공을 지금 롤러 중심 위치(방향은 TCP 방향)로 옮김."""
    M = fk(_q_now())
    p_ball = M[:3, 3] + M[:3, :3] @ ROLLER_IN_TCP
    if stage.GetPrimAtPath(TARGET_PATH):
        stage.RemovePrim(TARGET_PATH)
    s = UsdGeom.Sphere.Define(stage, TARGET_PATH)          # collision 없음 → 로봇과 안 부딪힘
    s.CreateRadiusAttr(TARGET_RADIUS)
    s.CreateDisplayColorAttr([Gf.Vec3f(1.0, 0.45, 0.0)])
    xf = UsdGeom.Xformable(s.GetPrim())
    xf.AddTranslateOp().Set(Gf.Vec3d(*[float(v) for v in p_ball]))
    print(f"[OK] target ball at roller center ({p_ball[0]:.3f}, {p_ball[1]:.3f}, {p_ball[2]:.3f})")
    q = Gf.Matrix3d(*M[:3, :3].T.flatten().tolist()).ExtractRotation().GetQuat()   # Gf 는 행=축 → 전치
    xf.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(q)
    follow["R_lock"] = M[:3, :3].copy()                    # 도구 방향 고정용
    follow["last"] = None


def _read_target():
    prim = stage.GetPrimAtPath(TARGET_PATH)
    if not prim or not prim.IsValid():
        return None, None
    m = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    t = m.ExtractTranslation()
    r = m.ExtractRotationMatrix()
    R = np.array([[r[i][j] for j in range(3)] for i in range(3)]).T     # 행=축 → 열=축
    return np.array([t[0], t[1], t[2]], float), R


def _set_follow(on):
    follow["on"] = on
    if on:
        _target_to_tool()
        print("[OK] Mouse target ON - select /World/TCP_Target, press W, drag the arrows")
    if follow_model.as_bool != on:
        follow_model.set_value(on)


def _on_update(*args, **kwargs):
    """매 프레임: 공이 움직였으면 IK 로 관절각 계산 → 슬라이더(=모터 목표) 갱신."""
    if not follow["on"]:
        return
    p, R = _read_target()
    if p is None:
        return
    key = (tuple(np.round(p, 5)), tuple(np.round(R, 4).flatten()))
    if key == follow["last"]:
        return                                              # 공이 안 움직였으면 계산 안 함
    follow["last"] = key
    R_goal = R if rot_model.as_bool else follow["R_lock"]
    p_tcp = p - R_goal @ ROLLER_IN_TCP                     # 공(롤러 중심) → TCP 목표
    q, perr = ik(_q_now(), p_tcp, R_goal)
    for n, v in zip(JOINTS, q):
        models[n].set_value(float(v))
    reach_label.text = f"reach error: {perr * 1000:.1f} mm" + ("  (out of reach)" if perr > 0.005 else "")


# =============================================================================
# 조종 창 (슬라이더 6개 + 버튼)
# =============================================================================
state = {"sel": "base"}
models, labels = {}, {}

window = ui.Window("RB10 Joint Teleop", width=460, height=420)
with window.frame:
    with ui.VStack(spacing=6):
        ui.Label("Mouse: drag sliders  |  Keys: 1-6 select, Up/Down +-1 deg, "
                 "Shift +-5 deg, R = WORK_POSE  |  Press Play to move",
                 word_wrap=True, height=36)
        for i, n in enumerate(JOINTS):
            with ui.HStack(height=26):
                labels[n] = ui.Label(f"  {i + 1} {n}", width=110)
                m = ui.SimpleFloatModel(_current_pendant_deg(n))
                ui.FloatSlider(model=m, min=-LIMIT_DEG, max=LIMIT_DEG, step=0.1)
                m.add_value_changed_fn(lambda mdl, name=n: _set_target(name, mdl.as_float))
                models[n] = m
        with ui.HStack(height=30, spacing=6):
            ui.Button("Reset to WORK_POSE",
                      clicked_fn=lambda: [models[n].set_value(WORK_POSE_DEG[n]) for n in JOINTS])
            ui.Button("All zero",
                      clicked_fn=lambda: [models[n].set_value(0.0) for n in JOINTS])
        ui.Separator(height=6)
        with ui.HStack(height=24, spacing=6):
            follow_model = ui.SimpleBoolModel(False)
            ui.CheckBox(model=follow_model, width=20)
            ui.Label("Mouse target (F): drag orange ball with W tool", width=0)
        with ui.HStack(height=24, spacing=6):
            rot_model = ui.SimpleBoolModel(False)
            ui.CheckBox(model=rot_model, width=20)
            ui.Label("Use target rotation (E tool). Off = keep tool facing wall", width=0)
        with ui.HStack(height=28, spacing=6):
            ui.Button("Target to tool", clicked_fn=lambda: _target_to_tool())
            reach_label = ui.Label("reach error: -")
follow_model.add_value_changed_fn(lambda m: _set_follow(m.as_bool) if m.as_bool != follow["on"] else None)


def _select(name):
    state["sel"] = name
    for i, n in enumerate(JOINTS):
        labels[n].text = f"{'>' if n == name else ' '} {i + 1} {n}"


_select("base")

# =============================================================================
# 키보드
# =============================================================================
_KEY_TO_JOINT = {
    carb.input.KeyboardInput.KEY_1: "base",
    carb.input.KeyboardInput.KEY_2: "shoulder",
    carb.input.KeyboardInput.KEY_3: "elbow",
    carb.input.KeyboardInput.KEY_4: "wrist1",
    carb.input.KeyboardInput.KEY_5: "wrist2",
    carb.input.KeyboardInput.KEY_6: "wrist3",
}


def _on_key(event, *args, **kwargs):
    if event.type not in (carb.input.KeyboardEventType.KEY_PRESS,
                          carb.input.KeyboardEventType.KEY_REPEAT):
        return True
    key = event.input
    if key in _KEY_TO_JOINT:
        _select(_KEY_TO_JOINT[key])
    elif key in (carb.input.KeyboardInput.UP, carb.input.KeyboardInput.DOWN):
        shift = bool(event.modifiers & carb.input.KEYBOARD_MODIFIER_FLAG_SHIFT)
        step = BIG_STEP_DEG if shift else STEP_DEG
        if key == carb.input.KeyboardInput.DOWN:
            step = -step
        m = models[state["sel"]]
        m.set_value(m.as_float + step)            # 슬라이더도 같이 움직이고, 모터 목표도 바뀜
    elif key == carb.input.KeyboardInput.R:
        for n in JOINTS:
            models[n].set_value(WORK_POSE_DEG[n])
        if follow["on"]:
            _target_to_tool()                     # 공도 팔 끝으로 같이 이동
    elif key == carb.input.KeyboardInput.F:
        _set_follow(not follow["on"])
    return True                                   # 다른 창(뷰포트 등)도 키를 계속 받게


_inp = carb.input.acquire_input_interface()
_kb = omni.appwindow.get_default_app_window().get_keyboard()
_sub = _inp.subscribe_to_keyboard_events(_kb, _on_key)

# 매 프레임 호출 (목표점 따라가기)
_update_sub = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
    _on_update, name="rb10_teleop_ik")

# 창·키보드·프레임 연결이 사라지지 않게 보관 (다음 Run 때 위에서 정리)
builtins._rb10_teleop = {"window": window, "inp": _inp, "kb": _kb, "sub": _sub,
                         "update_sub": _update_sub}
print("[OK] RB10 Joint Teleop window ready - press Play, then drag sliders, use keys, "
      "or turn on Mouse target (F)")
