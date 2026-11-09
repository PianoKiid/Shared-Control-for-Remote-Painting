"""Replace this module to experiment with another normal shared-control law.

SI units. Normal velocity is positive INTO the wall; gap positive OUTSIDE.
The operator command remains a velocity, never a force-target adjustment.
"""

from dataclasses import dataclass, fields
import math


@dataclass(frozen=True)
class Parameters:
    desired_force_N: float = 10.0
    force_gain_m_N_s: float = 0.002
    painting_authority: float = 0.9
    authority_tau_s: float = 0.1
    entropy_weight: float = 2.0
    max_normal_speed_m_s: float = 0.05
    contact_on_N: float = 1.0
    contact_off_N: float = 0.5
    input_deadband_m_s: float = 0.0005
    context_hold_s: float = 0.35
    contact_history_s: float = 2.0
    recovery_speed_m_s: float = 0.005
    recovery_gap_m: float = 0.006
    recovery_travel_m: float = 0.006
    recovery_timeout_s: float = 0.6
    painting_probability: float = 0.6

    def __post_init__(self):
        if any(
            not math.isfinite(getattr(self, f.name)) or getattr(self, f.name) < 0
            for f in fields(self)
        ):
            raise ValueError("Controller parameters must be finite and nonnegative")
        if (
            not 0 < self.painting_authority <= 1
            or not 0 < self.painting_probability <= 1
        ):
            raise ValueError("Authority/probability must be in (0,1]")
        if (
            not self.contact_off_N < self.contact_on_N
            or min(
                self.authority_tau_s, self.recovery_timeout_s, self.max_normal_speed_m_s
            )
            <= 0
        ):
            raise ValueError("Invalid hysteresis, rate or duration")


@dataclass(frozen=True)
class Observation:
    dt: float
    human: float
    force: float
    gap: float
    probabilities: object
    enabled: bool = True


@dataclass(frozen=True)
class Decision:
    command: float
    authority: float
    mode: str
    nominal: float
    contact: bool
    released: bool


class Controller:
    def __init__(self, params=None, condition="shared"):
        if condition not in ("manual", "probability", "shared"):
            raise ValueError("Unknown condition")
        self.params = params or Parameters()
        self.condition = condition
        self.reset()

    def reset(self):
        self.time = 0.0
        self.alpha = 0.0
        self.contact = False
        self.released = False
        self.last_contact = -math.inf
        self.last_paint = -math.inf
        self.outward = False
        self.previous_h = 0.0
        self.recovery_time = 0.0
        self.recovery_travel = 0.0
        self.recovery_blocked = False

    def step(self, o: Observation) -> Decision:
        p = self.params
        if (
            not all(math.isfinite(v) for v in (o.dt, o.human, o.force, o.gap))
            or not 0 < o.dt <= 0.2
            or o.force < 0
        ):
            raise ValueError("Invalid observation or control interval")
        prob = [float(v) for v in o.probabilities]
        if (
            len(prob) != 4
            or any(not math.isfinite(v) or v < 0 for v in prob)
            or abs(sum(prob) - 1) > 1e-5
        ):
            raise ValueError(
                "Expected normalized FREE/APPROACH/PAINTING/RETRACT probabilities"
            )
        self.time += o.dt
        h = max(-p.max_normal_speed_m_s, min(p.max_normal_speed_m_s, o.human))
        if o.force >= p.contact_on_N:
            self.contact = True
        elif o.force <= p.contact_off_N:
            self.contact = False
        if not o.enabled:
            self.alpha = 0.0
            self.previous_h = 0.0
            return Decision(0.0, 0.0, "disabled", 0.0, self.contact, self.released)
        inward = h > p.input_deadband_m_s
        outward = h < -p.input_deadband_m_s
        inward_edge = inward and self.previous_h <= p.input_deadband_m_s
        self.previous_h = h
        if self.contact:
            self.last_contact = self.time
            self.recovery_time = 0.0
            self.recovery_travel = 0.0
            self.recovery_blocked = False
            if prob[2] >= p.painting_probability:
                self.last_paint = self.time
        history = self.time - self.last_contact <= p.contact_history_s
        painting = self.time - self.last_paint <= p.context_hold_s
        if outward:
            self.outward = True
        if not self.contact and self.outward:
            self.released = True
        if inward:
            self.released = False
            self.outward = False
            if inward_edge:
                self.recovery_blocked = False
                self.recovery_time = 0.0
                self.recovery_travel = 0.0
        mode = "free"
        va = h
        if self.contact:
            mode = "contact"
            va = max(
                -p.max_normal_speed_m_s,
                min(
                    p.max_normal_speed_m_s,
                    p.force_gain_m_N_s * (p.desired_force_N - o.force),
                ),
            )
        elif (
            self.condition == "shared"
            and history
            and not self.released
            and not outward
            and (painting or inward)
            and o.gap <= p.recovery_gap_m
            and not self.recovery_blocked
        ):
            self.recovery_time += o.dt
            if (
                self.recovery_time > p.recovery_timeout_s
                or self.recovery_travel >= p.recovery_travel_m
            ):
                self.recovery_blocked = True
            else:
                mode = "recover"
                va = max(
                    h,
                    min(
                        p.recovery_speed_m_s,
                        (p.recovery_travel_m - self.recovery_travel) / o.dt,
                    ),
                )
        if self.released and not self.contact:
            mode = "released"
        entropy = -sum(v * math.log(v) for v in prob if v > 0) / math.log(4)
        belief = prob[2]
        if self.condition == "shared" and (
            (painting and self.contact) or mode == "recover"
        ):
            belief = max(belief, p.painting_probability)
        target = p.painting_authority * belief / (1 + p.entropy_weight * entropy)
        self.alpha += (1 - math.exp(-o.dt / p.authority_tau_s)) * (target - self.alpha)
        if mode not in ("contact", "recover") or self.condition == "manual":
            self.alpha = 0.0
        nominal = h + self.alpha * (va - h)
        command = (
            min(nominal, h) if self.condition == "shared" and self.outward else nominal
        )
        if mode == "recover":
            self.recovery_travel += max(0.0, command - h) * o.dt
        if self.condition == "manual":
            mode = "manual"
        return Decision(command, self.alpha, mode, nominal, self.contact, self.released)
