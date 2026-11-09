"""URDF-based kinematics in link0 coordinates; no hard-coded joint offsets."""

from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

JOINT_NAMES = ("base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3")
ROLLER_LINK = "single_roller_paint_eoat_no_camera_roller_contact_link"


def rotation(axis, angle):
    axis = np.asarray(axis, float)
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def origin(element):
    T = np.eye(4)
    if element is not None:
        T[:3, 3] = np.fromstring(element.get("xyz", "0 0 0"), sep=" ")
        r, p, y = np.fromstring(element.get("rpy", "0 0 0"), sep=" ")
        T[:3, :3] = (
            rotation([0, 0, 1], y) @ rotation([0, 1, 0], p) @ rotation([1, 0, 0], r)
        )
    return T


def rotvec(R):
    angle = np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))
    if angle < 1e-8:
        return np.zeros(3)
    if np.pi - angle < 1e-5:
        vals, vecs = np.linalg.eigh((R + np.eye(3)) / 2)
        return vecs[:, np.argmax(vals)] * angle
    return (
        np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
        * angle
        / (2 * np.sin(angle))
    )


class RobotGeometry:
    def __init__(self, path):
        self.path = Path(path)
        root = ET.parse(path).getroot()
        self.joints = {j.find("child").get("link"): j for j in root.findall("joint")}
        self.links = {l.get("name"): l for l in root.findall("link")}
        self.lower = np.full(6, -np.pi)
        self.upper = np.full(6, np.pi)
        for j in self.joints.values():
            if j.get("name") in JOINT_NAMES:
                i = JOINT_NAMES.index(j.get("name"))
                lim = j.find("limit")
                self.lower[i] = float(lim.get("lower"))
                self.upper[i] = float(lim.get("upper"))
        self.chains = {}
        for target in ("tcp", "single_roller_ft_link", ROLLER_LINK):
            chain = []
            current = target
            while current != "link0":
                j = self.joints[current]
                chain.insert(0, j)
                current = j.find("parent").get("link")
            self.chains[target] = [
                (
                    origin(j.find("origin")),
                    (
                        JOINT_NAMES.index(j.get("name"))
                        if j.get("name") in JOINT_NAMES
                        else None
                    ),
                    (
                        np.fromstring(j.find("axis").get("xyz"), sep=" ")
                        if j.find("axis") is not None
                        else None
                    ),
                )
                for j in chain
            ]
        collision = self.links[ROLLER_LINK].find("collision")
        self.roller_origin = origin(collision.find("origin"))
        cylinder = collision.find("geometry/cylinder")
        self.radius = float(cylinder.get("radius"))
        self.length = float(cylinder.get("length"))

    def fk(self, q, link="tcp"):
        q = np.asarray(q, float)
        if q.shape != (6,) or not np.isfinite(q).all():
            raise ValueError("Expected six finite radians")
        T = np.eye(4)
        for fixed, index, axis in self.chains[link]:
            T = T @ fixed
            if index is not None:
                R = np.eye(4)
                R[:3, :3] = rotation(axis, q[index])
                T = T @ R
        return T

    def tcp_jacobian(self, q):
        """Geometric Jacobian in base axes, with angular rows weighted by 0.3 m."""
        q = np.asarray(q, float)
        if q.shape != (6,) or not np.isfinite(q).all():
            raise ValueError("Expected six finite radians")
        T = np.eye(4)
        axes = np.zeros((6, 3))
        positions = np.zeros((6, 3))
        for fixed, index, axis in self.chains["tcp"]:
            T = T @ fixed
            if index is not None:
                axes[index] = T[:3, :3] @ axis
                positions[index] = T[:3, 3]
                R = np.eye(4)
                R[:3, :3] = rotation(axis, q[index])
                T = T @ R
        J = np.vstack((np.cross(axes, T[:3, 3] - positions).T, 0.3 * axes.T))
        return T, J

    def roller(self, q):
        T = self.fk(q, ROLLER_LINK) @ self.roller_origin
        return T[:3, 3], T[:3, 2]

    def gap(self, q, wall_x):
        center, axis = self.roller(q)
        a = abs(axis[0])
        return float(
            wall_x
            - center[0]
            - (self.radius * np.sqrt(max(0, 1 - a * a)) + self.length * 0.5 * a)
        )

    def training_force(self, q, reaction_world):
        """Convert robot reaction to the recorded force-on-environment FT axes."""
        return -self.fk(q, "single_roller_ft_link")[:3, :3].T @ np.asarray(
            reaction_world, float
        )

    def ik(self, seed, position, orientation, iterations=35):
        q = np.clip(np.asarray(seed, float).copy(), self.lower, self.upper)
        position = np.asarray(position, float)
        orientation = np.asarray(orientation, float)

        def error(q):
            T = self.fk(q)
            return np.r_[position - T[:3, 3], 0.3 * rotvec(orientation @ T[:3, :3].T)]

        for _ in range(iterations):
            T, J = self.tcp_jacobian(q)
            e = np.r_[position - T[:3, 3], 0.3 * rotvec(orientation @ T[:3, :3].T)]
            if np.linalg.norm(e) < 1e-5:
                break
            step = J.T @ np.linalg.solve(J @ J.T + 1e-5 * np.eye(6), e)
            q = np.clip(
                q + step * min(1, 0.15 / max(np.linalg.norm(step), 1e-12)),
                self.lower,
                self.upper,
            )
        return q, float(np.linalg.norm(error(q)))


def prepare_urdf(source, destination):
    """Create a portable import copy with link0=world, preserving original assets."""
    source = Path(source).resolve()
    destination = Path(destination)
    tree = ET.parse(source)
    root = tree.getroot()
    root.set("name", "painting_rb10")
    for mesh in root.findall(".//mesh"):
        path = (source.parent / mesh.get("filename")).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        mesh.set("filename", path.as_posix())
    root.find("joint[@name='support_to_rb10']/origin").set("rpy", "0 0 0")
    roller = root.find(f"link[@name='{ROLLER_LINK}']")
    if roller.find("inertial") is None:
        inertial = ET.SubElement(roller, "inertial")
        ET.SubElement(inertial, "origin", xyz="0 -0.018 0.07675", rpy="0 0 0")
        ET.SubElement(inertial, "mass", value=".12")
        ET.SubElement(
            inertial,
            "inertia",
            ixx=".00004",
            iyy=".00033",
            izz=".00033",
            ixy="0",
            ixz="0",
            iyz="0",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination
