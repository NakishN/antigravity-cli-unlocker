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
from antigravity_unlock.config import load_config, DEFAULT_PINNED_VERSION
from antigravity_unlock.pinner import init_pin, ensure_pinned, get_pinned_backup_path, get_agy_version
from antigravity_unlock.guardian import run_guardian
from antigravity_unlock.autostart import install_autostart, remove_autostart, autostart_status

def print_banner():
    print(f"""
╔══════════════════════════════════════════════════════╗
║     🚀 Antigravity CLI Unlocker v{__version__:<18} ║
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

    print("\n Version Pinning:")
    cfg = load_config()
    primary = get_primary_agy()
    pinned_bak = get_pinned_backup_path(primary) if primary else None
    print(f"  Target Version: {cfg.get('pinned_version', DEFAULT_PINNED_VERSION)}")
    print(f"  Auto-Patch:     {cfg.get('auto_patch', True)}")
    print(f"  Pinned Backup:  {'Present (' + pinned_bak + ')' if pinned_bak and os.path.exists(pinned_bak) else 'Not initialized'}")

    print("\n Autostart Status:")
    astat = autostart_status()
    print(f"  Platform:  {astat['platform']}")
    print(f"  Installed: {'Yes' if astat['installed'] else 'No'}")
    print(f"  Active:    {'Yes' if astat['active'] else 'No'}")
    if astat.get('path'):
        print(f"  Path:      {astat['path']}")
    if astat.get('detail'):
        print(f"  Detail:    {astat['detail']}")
    print("")

def main():
    parser = argparse.ArgumentParser(
        description=f"Antigravity CLI Unlocker v{__version__} - Bypass regional restrictions & pin agy version."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run agy wrapped with local split-tunnel proxy")
    run_parser.add_argument("agy_args", nargs=argparse.REMAINDER, help="Arguments passed directly to agy")

    # Command: patch
    patch_parser = subparsers.add_parser("patch", help="Apply patch to agy binary")
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

    # Command: guardian
    subparsers.add_parser("guardian", help="Run background guardian daemon to monitor agy binary version")

    # Command: autostart
    autostart_parser = subparsers.add_parser("autostart", help="Autostart service management")
    auto_sub = autostart_parser.add_subparsers(dest="autostart_subcommand", help="Autostart actions")
    auto_sub.add_parser("install", help="Install guardian service to autostart (systemd/schtasks/launchd)")
    auto_sub.add_parser("remove", help="Remove guardian service from autostart")
    auto_sub.add_parser("uninstall", help="Remove guardian service from autostart")
    auto_sub.add_parser("status", help="Show autostart service status")

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
        sys.exit(run_wrapped_command(cmd_args))

    elif args.command == "patch":
        print_banner()
        agy_path = get_primary_agy()
        if not agy_path:
            print("Error: agy binary not found.", file=sys.stderr)
            sys.exit(1)
        success, msg, _ = patch_binary(agy_path, dry_run=getattr(args, "dry_run", False), force=getattr(args, "force", False))
        print(f"Result: {msg}")
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
        print(f" {'✅' if success else '❌'} {msg}")
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
        else: # check
            dry = getattr(args, "dry_run", False)
            ok, msg, changed = ensure_pinned(dry_run=dry)
            print(f"Pin Check: {msg}")
            sys.exit(0 if ok else 1)

    elif args.command == "guardian":
        print_banner()
        sys.exit(run_guardian())

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
        # Default behavior: run status & enforce pinned patch
        print_banner()
        status_cmd()
        agy_path = get_primary_agy()
        if agy_path:
            print("Enforcing pinned version & patch...")
            ok, msg, _ = ensure_pinned()
            print(f"Result: {msg}")
            print("\nUsage tips:")
            print("  antigravity-unlock autostart install   (Install background version guardian autostart)")
            print("  antigravity-unlock pin init            (Initialize version pin backup)")
            print("  antigravity-unlock pin check           (Verify and enforce version pin)")
            print("  antigravity-unlock guardian            (Run background daemon foreground)")
            print("  antigravity-unlock restore             (Restore original binary)")

if __name__ == "__main__":
    main()
