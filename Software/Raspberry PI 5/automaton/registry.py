from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json, os, tempfile
from .protocol import Role

DEFAULT_PATH = Path.home() / ".config" / "automaton" / "rcb_registry.json"


@dataclass
class RegistryNode:
    uid: str
    # Physical CCB socket/channel.  This is meaningful hardware topology; Linux canX is not.
    channel: int | None = None
    # Informational last-observed netdev name for diagnostics only.
    interface: str = ""
    expected_hardware: str = "RCB-R1"
    enabled: bool = True


class RegistryConflict(RuntimeError):
    pass


class RcbRegistry:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self.protocol_version = 1
        self.nodes: dict[str, RegistryNode] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        obj = json.loads(self.path.read_text())
        self.protocol_version = int(obj.get("protocol_version", 1))
        nodes: dict[str, RegistryNode] = {}
        for role, data in obj.get("nodes", {}).items():
            # v0.1/v0.2 registries only had "interface". They remain readable; the physical
            # channel is learned on the next explicit pairing/registry update rather than
            # guessing that canN means channel N.
            nodes[role] = RegistryNode(
                uid=str(data["uid"]),
                channel=None if data.get("channel") is None else int(data["channel"]),
                interface=str(data.get("interface", "")),
                expected_hardware=str(data.get("expected_hardware", "RCB-R1")),
                enabled=bool(data.get("enabled", True)),
            )
        self.nodes = nodes

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        obj = {
            "protocol_version": self.protocol_version,
            "nodes": {k: asdict(v) for k, v in sorted(self.nodes.items())},
        }
        fd, tmp_name = tempfile.mkstemp(prefix="rcb_registry.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(obj, f, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def assign(self, role: Role, uid: int, interface: str, *, channel: int | None = None, replace: bool = False) -> None:
        role_name = role.name
        uid_hex = f"{uid:016X}"
        if role == Role.UNASSIGNED:
            raise RegistryConflict("UNASSIGNED is not a host registry role")
        if channel is not None and not 0 <= channel < 8:
            raise RegistryConflict("physical CCB channel must be 0..7")

        existing = self.nodes.get(role_name)
        if existing and existing.uid != uid_hex and not replace:
            raise RegistryConflict(f"role {role_name} already belongs to UID {existing.uid}; refusing silent remap")
        if existing and existing.uid == uid_hex and existing.channel is not None and channel is not None \
                and existing.channel != channel and not replace:
            raise RegistryConflict(
                f"{role_name}/UID {uid_hex} is registered on physical CCB channel {existing.channel}, "
                f"observed channel {channel}; refusing silent socket remap"
            )
        for other_role, node in self.nodes.items():
            if other_role != role_name and node.uid == uid_hex:
                raise RegistryConflict(f"UID {uid_hex} is already assigned to {other_role}")

        self.nodes[role_name] = RegistryNode(uid=uid_hex, channel=channel, interface=interface)

    def validate_observation(self, role: Role, uid: int, interface: str, channel: int | None = None) -> list[str]:
        problems: list[str] = []
        uid_hex = f"{uid:016X}"
        expected = self.nodes.get(role.name)
        if expected and expected.uid != uid_hex:
            problems.append(f"{role.name}: expected UID {expected.uid}, observed {uid_hex}")
        if expected and expected.channel is not None and channel is not None and expected.channel != channel:
            problems.append(
                f"{role.name}: expected physical CCB channel {expected.channel}, observed {channel}"
            )
        for other_role, node in self.nodes.items():
            if other_role != role.name and node.uid == uid_hex:
                problems.append(f"UID {uid_hex} is registered as {other_role}, not {role.name}")
        # A changed Linux netdev name alone is deliberately not a conflict.
        return problems

    def update_observed_interface(self, role: Role, uid: int, interface: str, channel: int | None) -> None:
        """Refresh diagnostic interface naming only after UID/topology validation succeeds."""
        problems = self.validate_observation(role, uid, interface, channel)
        if problems:
            raise RegistryConflict("; ".join(problems))
        node = self.nodes.get(role.name)
        if node is not None:
            node.interface = interface
            if node.channel is None and channel is not None:
                node.channel = channel
