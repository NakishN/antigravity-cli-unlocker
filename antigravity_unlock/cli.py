"""
CLI Interface for Antigravity CLI Unlocker.
"""

import sys
import os
import argparse

from antigravity_unlock import __version__
from antigravity_unlock.discovery import find_agy_binaries, get_primary_agy
from antigravity_unlock.patcher import patch_binary, restore_binary, compute_sha256, get_backup_path
from antigravity_unlock.proxy import run_proxy_server
from antigravity_unlock.runner import run_wrapped_command
from antigravity_unlock.ca_manager import get_or_create_ca, install_ca_system
from antigravity_unlock.config import (
    DEFAULT_PINNED_VERSION,
    DEFAULT_STRATEGY,
    STRATEGY_AUTO,
    STRATEGY_IN_PLACE,
    STRATEGY_PIN,
    load_config,
)
from antigravity_unlock.pinner import (
    enforce_strategy,
    ensure_pinned,
    get_agy_version,
    get_pinned_backup_path,
    init_pin,
    set_strategy,
)
from antigravity_unlock.guardian import run_guardian
from antigravity_unlock.autostart import install_autostart, remove_autostart, autostart_status
from antigravity_unlock.endpoint import apply_ide_endpoint, remove_ide_endpoint, DAILY_ENDPOINT
from antigravity_unlock.discovery import find_ide_installations
from antigravity_unlock.ipv4_priority import apply_ipv4_priority, remove_ipv4_priority, ipv4_preferred, has_global_ipv6

STRATEGY_CHOICES = [STRATEGY_AUTO, STRATEGY_IN_PLACE, STRATEGY_PIN]


def print_banner():
    print(f"""
╔══════════════════════════════════════════════════════╗
║     Antigravity CLI Unlocker v{__version__:<22} ║
║   Cross-Platform Split-Tunnel Proxy & Patcher        ║
╚══════════════════════════════════════════════════════╝
""")


def status_cmd():
    print_banner()
    binaries = find_agy_binaries()
    if not binaries:
        print(" [!] No agy binaries found on system.")
    else:
        print(f" Found {len(binaries)} agy binary candidate(s):")
        for i, b in enumerate(binaries, 1):
            sha = compute_sha256(b)
            bak = get_backup_path(b)
            has_bak = os.path.exists(bak)
            ver = get_agy_version(b) or "unknown"
            print(f"  {i}. {b}")
            print(f"     Version: {ver}")
            print(f"     SHA-256: {sha}")
            print(f"     Backup:  {'Present (' + bak + ')' if has_bak else 'Not created'}")

    print("\n Patch Strategy & Version Pinning:")
    cfg = load_config()
    primary = get_primary_agy()
    pinned_bak = get_pinned_backup_path(primary) if primary else None
    strat = cfg.get("strategy", DEFAULT_STRATEGY)
    if strat == STRATEGY_AUTO:
        strat_desc = "Auto: In-place with fallback to pinned version"
    elif strat == STRATEGY_IN_PLACE:
        strat_desc = "In-place: Patch installed binary on the spot"
    else:
        strat_desc = "Pin: Enforce rollback and lock to pinned version"

    print(f"  Active Strategy: {strat} ({strat_desc})")
    print(f"  Fallback Version:{cfg.get('pinned_version', DEFAULT_PINNED_VERSION)}")
    print(f"  Auto-Patch:      {cfg.get('auto_patch', True)}")
    print(f"  Pinned Backup:   {'Present (' + pinned_bak + ')' if pinned_bak and os.path.exists(pinned_bak) else 'Not initialized'}")

    print("\n Autostart Status:")
    astat = autostart_status()
    print(f"  Platform:  {astat['platform']}")
    print(f"  Installed: {'Yes' if astat['installed'] else 'No'}")
    print(f"  Active:    {'Yes' if astat['active'] else 'No'}")
    if astat.get('path'):
        print(f"  Path:      {astat['path']}")
    if astat.get('detail'):
        print(f"  Detail:    {astat['detail']}")

    print("\n IPv4 Priority:")
    print(f"  Global IPv6:    {'Yes' if has_global_ipv6() else 'No'}")
    print(f"  IPv4 preferred: {'Yes' if ipv4_preferred() else 'No'}")

    print("\n CloudCode Endpoint Override:")
    print(f"  Target:    {DAILY_ENDPOINT}")
    from antigravity_unlock.endpoint import _ide_settings_path, IDE_SETTING
    import re as _re
    ide_installs = find_ide_installations()
    for ide_dir in ide_installs:
        sp = _ide_settings_path(ide_dir)
        if sp and os.path.isfile(sp):
            with open(sp, "r", encoding="utf-8", errors="ignore") as _f:
                _txt = _f.read()
            _m = _re.search(r'"' + _re.escape(IDE_SETTING) + r'"\s*:\s*"([^"]*)"', _txt)
            current = _m.group(1) if _m else "not set"
            status = "OK" if current == DAILY_ENDPOINT else f"needs update ({current})"
        else:
            status = "settings file not found"
            sp = sp or "(unknown)"
        print(f"  IDE ({ide_dir}):")
        print(f"    Settings: {sp}")
        print(f"    Status:   {status}")
    if not ide_installs:
        print("  No IDE installations found.")
    print("")


def main():
    parser = argparse.ArgumentParser(
        description=f"Antigravity CLI Unlocker v{__version__} - Bypass regional restrictions & manage patch strategy."
    )
    parser.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default=None,
        help="Patch strategy: 'auto' (default: in-place with 1.1.9 fallback), 'in_place' (patch current), 'pin' (lock 1.1.9)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run agy wrapped with local split-tunnel proxy")
    run_parser.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default=None,
        help="Strategy override: 'auto' (default), 'in_place', or 'pin'",
    )
    run_parser.add_argument("agy_args", nargs=argparse.REMAINDER, help="Arguments passed directly to agy")

    # Command: patch
    patch_parser = subparsers.add_parser("patch", help="Apply patch to agy binary in-place")
    patch_parser.add_argument("--dry-run", action="store_true", help="Verification mode without writing changes")
    patch_parser.add_argument("--force", action="store_true", help="Force patch attempt")

    # Command: restore
    subparsers.add_parser("restore", help="Restore original agy binary from backup")

    # Command: proxy
    proxy_parser = subparsers.add_parser("proxy", help="Run standalone Split-Tunnel proxy server")
    proxy_parser.add_argument("--host", default="127.0.0.1", help="Proxy host (default: 127.0.0.1)")
    proxy_parser.add_argument("--port", type=int, default=18888, help="Proxy port (default: 18888)")

    # Command: install-ca
    subparsers.add_parser("install-ca", help="Install local MITM CA certificate into system trust store")

    # Command: status
    subparsers.add_parser("status", help="Show system agy binaries, patch, pin, and autostart status")

    # Command: pin
    pin_parser = subparsers.add_parser("pin", help="Version pinning management")
    pin_subparsers = pin_parser.add_subparsers(dest="pin_subcommand", help="Pin actions")

    pin_init_p = pin_subparsers.add_parser("init", help="Initialize pin backup for current/target agy binary")
    pin_init_p.add_argument("--version", default=None, help="Version string to pin (default: 1.1.9)")
    pin_init_p.add_argument("--source", default=None, help="Path to source binary/backup")

    pin_check_p = pin_subparsers.add_parser("check", help="Check agy binary and enforce pinned version")
    pin_check_p.add_argument("--dry-run", action="store_true", help="Dry run check without writing")

    pin_strat_p = pin_subparsers.add_parser("strategy", help="Set active patch strategy in configuration")
    pin_strat_p.add_argument("mode", choices=STRATEGY_CHOICES, help="Strategy mode: 'auto', 'in_place', or 'pin'")

    # Command: guardian
    guardian_parser = subparsers.add_parser("guardian", help="Run background guardian daemon to monitor agy binary")
    guardian_parser.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default=None,
        help="Strategy override: 'auto', 'in_place', or 'pin'",
    )

    # Command: autostart
    autostart_parser = subparsers.add_parser("autostart", help="Autostart service management")
    auto_sub = autostart_parser.add_subparsers(dest="autostart_subcommand", help="Autostart actions")
    auto_sub.add_parser("install", help="Install guardian service to autostart (systemd/schtasks/launchd)")
    auto_sub.add_parser("remove", help="Remove guardian service from autostart")
    auto_sub.add_parser("uninstall", help="Remove guardian service from autostart")
    auto_sub.add_parser("status", help="Show autostart service status")

    # Command: ipv4
    ipv4_parser = subparsers.add_parser("ipv4", help="Manage IPv4 priority over IPv6")
    ipv4_sub = ipv4_parser.add_subparsers(dest="ipv4_subcommand", help="IPv4 actions")
    ipv4_sub.add_parser("apply", help="Prefer IPv4 when no global IPv6 is available")
    ipv4_sub.add_parser("remove", help="Remove IPv4 priority override")
    ipv4_sub.add_parser("status", help="Show current IPv4 priority status")

    # Command: endpoint
    endpoint_parser = subparsers.add_parser("endpoint", help="Manage CloudCode endpoint override for IDE")
    ep_sub = endpoint_parser.add_subparsers(dest="endpoint_subcommand", help="Endpoint actions")
    ep_sub.add_parser("apply", help=f"Set IDE endpoint to {DAILY_ENDPOINT}")
    ep_sub.add_parser("remove", help="Remove IDE endpoint override")
    ep_sub.add_parser("status", help="Show current endpoint status")

    # Legacy & convenience flags
    parser.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--restore", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pin-init", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pin-check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--guardian", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install-autostart", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--remove-autostart", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--autostart-status", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    args, unknown = parser.parse_known_args()

    # Dispatch legacy flags
    if args.restore:
        args.command = "restore"
    elif args.pin_init:
        args.command = "pin"
        args.pin_subcommand = "init"
    elif args.pin_check:
        args.command = "pin"
        args.pin_subcommand = "check"
    elif args.guardian:
        args.command = "guardian"
    elif args.autostart or args.install_autostart:
        args.command = "autostart"
        args.autostart_subcommand = "install"
    elif args.remove_autostart:
        args.command = "autostart"
        args.autostart_subcommand = "remove"
    elif args.autostart_status:
        args.command = "autostart"
        args.autostart_subcommand = "status"
    elif args.dry_run or args.force:
        if not args.command:
            args.command = "patch"

    if args.command == "run":
        cmd_args = args.agy_args
        if cmd_args and cmd_args[0] == "--":
            cmd_args = cmd_args[1:]
        strategy = getattr(args, "strategy", None)
        sys.exit(run_wrapped_command(cmd_args, strategy=strategy))

    elif args.command == "patch":
        print_banner()
        agy_path = get_primary_agy()
        if not agy_path:
            print("Error: agy binary not found.", file=sys.stderr)
            sys.exit(1)
        success, msg, _ = patch_binary(agy_path, dry_run=getattr(args, "dry_run", False), force=getattr(args, "force", False))
        print(f"Result: {msg}")
        for ide_dir in find_ide_installations():
            ok, ep_msg = apply_ide_endpoint(ide_dir)
            if ep_msg:
                print(f"Endpoint ({ide_dir}): {ep_msg}")
        sys.exit(0 if success else 1)

    elif args.command == "restore":
        print_banner()
        agy_path = get_primary_agy()
        if not agy_path:
            print("Error: agy binary not found.", file=sys.stderr)
            sys.exit(1)
        success, msg = restore_binary(agy_path)
        print(f"Result: {msg}")
        sys.exit(0 if success else 1)

    elif args.command == "proxy":
        print_banner()
        print(f"Starting Split-Tunnel Proxy on http://{args.host}:{args.port}...")
        run_proxy_server(host=args.host, port=args.port)

    elif args.command == "install-ca":
        print_banner()
        _, _, ca_cert_path = get_or_create_ca()
        print(f" CA certificate: {ca_cert_path}")
        print(" Installing into system trust store...")
        success, msg = install_ca_system(ca_cert_path)
        print(f" {'Success' if success else 'Failed'}: {msg}")
        sys.exit(0 if success else 1)

    elif args.command == "status":
        status_cmd()

    elif args.command == "pin":
        sub = getattr(args, "pin_subcommand", None) or "check"
        print_banner()
        if sub == "init":
            ver = getattr(args, "version", None)
            src = getattr(args, "source", None)
            ok, msg = init_pin(pinned_version=ver, source_path=src)
            print(f"Pin Init: {msg}")
            sys.exit(0 if ok else 1)
        elif sub == "strategy":
            mode = getattr(args, "mode", None)
            ok, msg = set_strategy(mode)
            print(f"Strategy: {msg}")
            sys.exit(0 if ok else 1)
        else:  # check
            dry = getattr(args, "dry_run", False)
            ok, msg, changed = ensure_pinned(dry_run=dry)
            print(f"Pin Check: {msg}")
            sys.exit(0 if ok else 1)

    elif args.command == "guardian":
        print_banner()
        strategy = getattr(args, "strategy", None)
        sys.exit(run_guardian(strategy=strategy))

    elif args.command == "ipv4":
        sub = getattr(args, "ipv4_subcommand", None) or "status"
        print_banner()
        if sub == "apply":
            ok, msg = apply_ipv4_priority()
            print(f"  {msg}")
            sys.exit(0 if ok else 1)
        elif sub == "remove":
            ok, msg = remove_ipv4_priority()
            print(f"  {msg}")
            sys.exit(0 if ok else 1)
        else:
            print(f"  Global IPv6:   {'Yes' if has_global_ipv6() else 'No'}")
            print(f"  IPv4 preferred: {'Yes' if ipv4_preferred() else 'No'}")
            sys.exit(0)

    elif args.command == "endpoint":
        sub = getattr(args, "endpoint_subcommand", None) or "status"
        print_banner()
        if sub == "apply":
            found = False
            for ide_dir in find_ide_installations():
                found = True
                ok, msg = apply_ide_endpoint(ide_dir)
                print(f"  {ide_dir}: {msg}")
            if not found:
                print("  No IDE installations found.")
            sys.exit(0)
        elif sub == "remove":
            found = False
            for ide_dir in find_ide_installations():
                found = True
                ok, msg = remove_ide_endpoint(ide_dir)
                print(f"  {ide_dir}: {msg}")
            if not found:
                print("  No IDE installations found.")
            sys.exit(0)
        else:
            status_cmd()

    elif args.command == "autostart":
        sub = getattr(args, "autostart_subcommand", None) or "status"
        if sub == "install":
            print_banner()
            ok, msg = install_autostart()
            print(f"Autostart Install: {msg}")
            sys.exit(0 if ok else 1)
        elif sub in ("remove", "uninstall"):
            print_banner()
            ok, msg = remove_autostart()
            print(f"Autostart Remove: {msg}")
            sys.exit(0 if ok else 1)
        else:
            status_cmd()

    else:
        # Default behavior: run status & enforce configured strategy
        print_banner()
        status_cmd()
        agy_path = get_primary_agy()
        if agy_path:
            strategy = getattr(args, "strategy", None)
            cfg = load_config()
            active_strat = strategy or cfg.get("strategy", DEFAULT_STRATEGY)
            print(f"Enforcing active strategy '{active_strat}'...")
            ok, msg, _ = enforce_strategy(strategy=active_strat)
            print(f"Result: {msg}")
            for ide_dir in find_ide_installations():
                ok, ep_msg = apply_ide_endpoint(ide_dir)
                if ep_msg:
                    print(f"Endpoint ({ide_dir}): {ep_msg}")
            print("\nUsage tips:")
            print("  antigravity-unlock --strategy auto     (Auto: in-place with 1.1.9 fallback)")
            print("  antigravity-unlock --strategy in_place (Patch installed agy in-place)")
            print("  antigravity-unlock --strategy pin      (Restore and lock agy 1.1.9)")
            print("  antigravity-unlock pin strategy auto   (Set default strategy in config)")
            print("  antigravity-unlock autostart install   (Install background guardian)")
            print("  antigravity-unlock restore             (Restore original binary)")


if __name__ == "__main__":
    main()
