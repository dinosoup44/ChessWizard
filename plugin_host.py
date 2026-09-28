"""Explicit-profile CLI and versioned worker host; never starts the desktop."""
import argparse
from contextlib import redirect_stdout
from dataclasses import asdict
from importlib import metadata
import json
import os
from pathlib import Path
import sys
from chesswizard_version import VERSION
from application_lifetime import retain_application_lifetime
from chesswizard_plugin_api import API_VERSION, MaterialFacts, PositionContext
from plugin_admission import descriptor_matches, request_is_current, selected_installation
from plugin_discovery import discover
from plugin_models import PluginLimits
from plugin_protocol import PROTOCOL_VERSION, encode_message, validate_context
from plugin_repository import PluginRepository
from plugin_state import decode_json


def _worker() -> int:
    sys.dont_write_bytecode = True
    limits = PluginLimits()
    nonce, phase = "", "discovery"

    def emit(kind: str, **fields: object) -> None:
        payload = encode_message(dict(protocol_version=PROTOCOL_VERSION, nonce=nonce, kind=kind, **fields), limits.max_message_bytes)
        sys.__stdout__.buffer.write(payload + b"\n")
        sys.__stdout__.buffer.flush()

    def advance(value: str) -> None:
        nonlocal phase
        phase = value
        emit("phase", phase=phase)

    try:
        raw = sys.stdin.buffer.read(limits.max_message_bytes + 1)
        if len(raw) > limits.max_message_bytes:
            raise ValueError("Input bound")
        request = decode_json(raw)
        nonce = request.get("nonce", "")
        if request.get("protocol_version") != PROTOCOL_VERSION or not isinstance(nonce, str) or len(nonce) != 32:
            raise ValueError("Unsupported protocol identity")
        site = Path(request["site"])
        if request["operation"] == "discover":
            descriptor = discover(site)
            emit("result", payload={"descriptor": asdict(descriptor), "plugin_modules_loaded":
                                    [name for name in sys.modules if name == descriptor.entry_point.split(":")[0]]})
            return 0
        if request["operation"] != "analyze":
            raise ValueError("Unsupported operation")
        repository = PluginRepository(Path(request["profile"]))
        state = repository.read()
        receipt = selected_installation(state, request["plugin_id"])
        requested = state.requested[receipt.plugin_id]
        if not request_is_current(state, receipt, requested):
            raise PermissionError("Disabled or untrusted")
        if request.get("installation_id", receipt.installation_id) != receipt.installation_id or request.get("generation", requested.generation) != requested.generation:
            raise PermissionError("Stale request")
        if repository.verify(receipt) != site:
            raise ValueError("Wrong installation")
        descriptor = discover(site)
        if not descriptor.compatible or not descriptor_matches(receipt, descriptor):
            raise ValueError("Incompatible metadata")
        context = PositionContext(**request["context"])
        validate_context(context)
        # No site.addsitedir: plugin wheels cannot introduce executable .pth hooks.
        sys.path.append(str(site))
        point = next(point for dist in metadata.distributions(path=[str(site)]) for point in dist.entry_points
                     if point.group == "chesswizard.plugins" and point.name == descriptor.plugin_id)
        advance("import")
        with redirect_stdout(sys.stderr):
            plugin = point.load()()
            try:
                advance("invoke")
                result = plugin.analyze(context)
                if not isinstance(result, MaterialFacts):
                    raise TypeError("Unsupported API result")
            except BaseException:
                advance("shutdown")
                plugin.close()
                phase = "invoke"
                raise
            else:
                advance("shutdown")
                plugin.close()
        emit("result", payload={"result": asdict(result), "worker_pid": os.getpid()})
        return 0
    except BaseException as error:
        # Plugin exception text and context never cross the diagnostic boundary.
        emit("error", phase=phase, error_type=type(error).__name__)
        return 1


def main(argv: list[str] | None = None) -> int:
    """Run one explicit-profile management action or isolated worker request.

    Args:
        argv: Optional CLI arguments.

    Returns:
        Zero on success; one for a bounded, isolated failure.
    """
    try:
        retain_application_lifetime()
    except RuntimeError as error:
        print(json.dumps({"error": "ServicingActive", "message": str(error)}))
        return 21
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("worker", "info", "install", "replace", "list", "enable", "disable", "analyze", "remove", "cleanup"))
    parser.add_argument("target", nargs="?")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--installation-id")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--acknowledge-code-trust", action="store_true")
    parser.add_argument("--fen")
    parser.add_argument("--request-id", default="plugin-position")
    args = parser.parse_args(argv)
    if args.action == "worker":
        return _worker()
    service = None
    try:
        if args.action == "info":
            result = {"frozen": bool(getattr(sys, "frozen", False)), "api_version": API_VERSION, "application_version": VERSION,
                      "python": sys.version, "executable": sys.executable,
                      "plugin_packages_loaded": [name for name in sys.modules if name.startswith("chesswizard_plugin_") and not name.startswith("chesswizard_plugin_api")]}
        else:
            from plugin_service import PluginService
            if args.profile is None or not args.profile.is_absolute():
                raise ValueError("An explicit absolute --profile is required")
            service = PluginService(args.profile)
            if args.action == "install":
                result = service.install(Path(args.target))
            elif args.action == "replace":
                if args.wheel is None:
                    raise ValueError("--wheel is required")
                result = service.replace(args.target, args.wheel)
            elif args.action == "list":
                snapshot = service.scan()
                result = asdict(snapshot)
            elif args.action in {"enable", "disable"}:
                result = {"changed": service.set_enabled(args.target, args.action == "enable", acknowledge_trust=args.acknowledge_code_trust)}
            elif args.action == "analyze":
                if not args.fen:
                    raise ValueError("--fen is required")
                result = {"result": asdict(service.analyze(args.target, PositionContext(args.request_id, args.fen))), "validated_by_core": True}
            elif args.action == "cleanup":
                result = {"cleaned": service.cleanup(args.target)}
            else:
                service.remove(args.target, installation_id=args.installation_id)
                result = {"removed": args.target}
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)[:512]}))
        return 1
    finally:
        if service is not None:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
