from __future__ import annotations
import argparse
import json
from pathlib import Path

from .logging_setup import configure
from .manager import CanManager
from .protocol import Role
from .registry import RcbRegistry, RegistryConflict
from .can_topology import discover_ccb_channels, ordered_interfaces
from .settings import DEFAULT_CONFIG_PATH, load_settings


def role_arg(value: str) -> Role:
    try:
        return Role[value.upper()]
    except KeyError as exc:
        raise argparse.ArgumentTypeError(f"unknown role {value}") from exc


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="automaton-host")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="override registry path from automaton.toml",
    )
    p.add_argument("--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover")
    d.add_argument("--interfaces", nargs="+", default=None)
    d.add_argument("--duration", type=float, default=2.0)

    pair = sub.add_parser("pair")
    pair.add_argument("role", type=role_arg)
    pair.add_argument("--interfaces", nargs="+", default=None)
    pair.add_argument("--timeout", type=float, default=30.0)
    pair.add_argument("--replace", action="store_true", help="explicitly replace an existing role mapping")

    sub.add_parser("topology")
    sub.add_parser("list")
    return p


def resolve_interfaces(settings, explicit: list[str] | None) -> tuple[str, ...]:
    if explicit:
        return tuple(explicit)
    if settings.can.auto_discover_by_spi:
        mapping = discover_ccb_channels()
        if mapping:
            return ordered_interfaces(mapping, require_all=False)
    return settings.can.interfaces


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    configure(args.verbose)
    settings = load_settings(args.config)
    registry_path = args.registry or settings.paths.registry

    if args.cmd == "topology":
        mapping = discover_ccb_channels()
        if not mapping:
            print("No Automaton spi0.<CS> CAN topology was discovered in sysfs.")
            return 1
        for channel, iface in sorted(mapping.items()):
            print(f"CCB channel {channel}: {iface}")
        return 0

    reg = RcbRegistry(registry_path)
    reg.load()

    if args.cmd == "list":
        print(json.dumps({k: vars(v) for k, v in reg.nodes.items()}, indent=2, sort_keys=True))
        return 0

    interfaces = resolve_interfaces(settings, args.interfaces)

    if args.cmd == "discover":
        with CanManager(list(interfaces)) as mgr:
            nodes = mgr.discover(args.duration)
        topology = discover_ccb_channels()
        interface_to_channel = {name: ch for ch, name in topology.items()}
        for iface, node in sorted(nodes.items()):
            h = node.hello
            channel = interface_to_channel.get(iface)
            channel_text = f" ch={channel}" if channel is not None else ""
            print(
                f"{iface}:{channel_text} UID={h.uid:016X} role={h.role.name} "
                f"fw={'.'.join(map(str, h.firmware))} state={h.state.name} faults=0x{int(h.faults):08X}"
            )
        return 0

    if args.cmd == "pair":
        print(f"Press IDENTIFY on the RCB that should be assigned to {args.role.name}.")
        with CanManager(list(interfaces)) as mgr:
            mgr.start_sessions()
            iface, uid = mgr.wait_for_identify(args.timeout)
            print(f"IDENTIFY received: {iface} UID={uid:016X}")
            topology = discover_ccb_channels()
            interface_to_channel = {name: ch for ch, name in topology.items()}
            channel = interface_to_channel.get(iface)
            try:
                reg.assign(args.role, uid, iface, channel=channel, replace=args.replace)
            except RegistryConflict as exc:
                print(f"PAIRING BLOCKED: {exc}")
                return 2
            result = mgr.set_role(iface, args.role)
            if result.name != "OK":
                print(f"RCB rejected SET_ROLE: {result.name}; registry not saved")
                return 3
            reg.save()
            print(
                f"Paired {args.role.name} -> UID={uid:016X} on {iface}"
                + (f" / CCB channel {channel}" if channel is not None else "")
                + ". Node remains disarmed."
            )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
