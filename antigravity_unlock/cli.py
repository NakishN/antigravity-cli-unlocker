"""
CLI Interface for Antigravity CLI Unlocker.
"""

import sys
import os
import argparse

from . import __version__
from .discovery import find_agy_binaries, get_primary_agy
from .patcher import patch_binary, restore_binary, compute_sha256, get_backup_path
from .proxy import run_proxy_server
from .runner import run_wrapped_command

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
        return

    print(f" Found {len(binaries)} agy binary candidate(s):")
    for i, b in enumerate(binaries, 1):
        sha = compute_sha256(b)
        bak = get_backup_path(b)
        has_bak = os.path.exists(bak)
        print(f"  {i}. {b}")
        print(f"     SHA-256: {sha}")
        print(f"     Backup:  {'Present (' + bak + ')' if has_bak else 'Not created'}")
    print("")

def main():
    parser = argparse.ArgumentParser(
        description=f"Antigravity CLI Unlocker v{__version__} - Bypass regional restrictions for Google Antigravity CLI & IDE."
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
    restore_parser = subparsers.add_parser("restore", help="Restore original agy binary from backup")

    # Command: proxy
    proxy_parser = subparsers.add_parser("proxy", help="Run standalone Split-Tunnel proxy server")
    proxy_parser.add_argument("--host", default="127.0.0.1", help="Proxy host (default: 127.0.0.1)")
    proxy_parser.add_argument("--port", type=int, default=18888, help="Proxy port (default: 18888)")

    # Command: status
    subparsers.add_parser("status", help="Show system agy binaries and patch status")

    # Legacy flag support
    parser.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--restore", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    args, unknown = parser.parse_known_args()

    # Legacy flags handling
    if args.restore:
        args.command = "restore"
    elif args.dry_run or args.force:
        args.command = "patch"

    if args.command == "run":
        # Remove leading '--' if passed
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
        success, msg, _ = patch_binary(agy_path, dry_run=args.dry_run, force=args.force)
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

    elif args.command == "status":
        status_cmd()

    else:
        # Default behavior: run status + patch
        print_banner()
        status_cmd()
        agy_path = get_primary_agy()
        if agy_path:
            print("Applying automatic binary patch...")
            success, msg, _ = patch_binary(agy_path)
            print(f"Patch Result: {msg}")
            print("\nUsage tips:")
            print("  antigravity-unlock run -- agy login   (Run agy with split-tunnel proxy)")
            print("  antigravity-unlock restore            (Restore original binary)")

if __name__ == "__main__":
    main()
