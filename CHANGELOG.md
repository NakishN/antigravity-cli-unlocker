# Changelog

All notable changes to the Antigravity CLI Unlocker project will be documented in this file.

## [1.2.0] - 2026-08-21

### Added
- **Multi-Strategy Patch System**: Added user-selectable patch strategies (`auto`, `in_place`, `pin`):
  - `auto` (Default): Attempts in-place machine code patching on the installed version; gracefully falls back to pinned `1.1.9` if an unsupported version is encountered.
  - `in_place`: Directly patches the installed `agy` binary without rollback or downgrade.
  - `pin`: Strictly enforces rolling back to and locking the verified `1.1.9` release.
- **Machine Code Eligibility Patch for v1.1.17+**: Added x86_64 machine code `.text` byte patches for `backend.(*AuthStatus).EligibilityError` and `backend.IneligibilityFromResult` to completely bypass Go runtime eligibility checks in newer stripped binaries.
- **CLI Strategy Options**: Added `--strategy {auto,in_place,pin}` flag to CLI commands and `pin strategy` subcommand to save default preference.

### Fixed
- **Pinner Configuration**: Resolved size and checksum mismatches in `config.json` during binary pinning cycles.

## [1.1.0] - 2026-08-17

### Added
- **Version Pinning System**: Added `agy` binary version pinning with automatic rollback protection.
- **Guardian Daemon**: Background monitor to enforce pinned versions and prevent automatic client overwrites.
- **Autostart Service**: Cross-platform service management (systemd, Windows Task Scheduler, macOS launchd).
- **Atomic File Replacement**: Safe binary substitution on Linux preventing `ETXTBSY` (Text file busy) errors.

## [1.0.1] - 2026-08-06

### Fixed
- **Smart DNS Resolution in SplitTunnelProxy**: Integrated a pure-Python UDP DNS A-record resolver with in-memory TTL caching. Target Google API endpoints are resolved via Smart DNS queries instead of using the DNS server IP as a TCP target, eliminating TLS certificate verification errors (`*.xbox-dns.ru`).
- **Direct Auth Routing**: Removed `~accounts.google.com` from `systemd-resolved` domain rules in `antigravity_unlock_linux.sh` to preserve direct authentication.

## [3.0.0] - 2026-08-05

### Added
- **Split-Tunnel Local Micro-Proxy**: Built-in async HTTP/SOCKS5 proxy server. Bypasses geoblocks for `generativelanguage.googleapis.com` while maintaining `DIRECT` unproxied connections for authentication domains (`accounts.google.com`, `oauth2.googleapis.com`).
- **Run-Wrapped CLI Mode**: Execute `antigravity-unlock run -- agy <args>` without root/administrator privileges or system-wide DNS changes.
- **Modular Python Architecture**: Refactored monolithic script into a clean `antigravity_unlock` Python package with `discovery`, `patcher`, `proxy`, `runner`, and `cli` modules.
- **Registry & Wildcard Byte Patcher**: Added `versions.json` registry with exact SHA-256 offsets and wildcard pattern matching fallback.
- **Standalone Binary & AppImage Builds**: Added PyInstaller script (`packaging/build_binaries.py`) and Linux AppImage packager (`packaging/build_appimage.sh`).
- **GitHub Release Automation**: Workflow (`.github/workflows/release.yml`) for automatic matrix builds of AppImage, Windows `.exe`, and standalone executables.
- **Automated Unit Testing Suite**: Added unittest suite (`tests/test_patcher.py`, `tests/test_proxy.py`).

## [2.2.0] - 2026-08-03

### Added
- **Modular Core**: Refactored core Python patcher (`antigravity_unlock.py`) with `--dry-run`, `--force`, and `--restore` capabilities.
- **SHA-256 Verification**: Automatic SHA-256 calculation and verification before and after binary patching.
- **Logging**: Integrated persistent file logging to `~/.local/share/antigravity-unlocker/unlocker.log`.
- **Windows Default Route Detection**: Enhanced PowerShell script to detect default interface via `Get-NetRoute -DestinationPrefix "0.0.0.0/0"`.
- **macOS Compatibility**: Added candidate paths for macOS Antigravity CLI installations.
- **CI/CD Integration**: Added GitHub Actions workflow (`.github/workflows/ci.yml`) for automated linting and ShellCheck validation.
- **Strict Documentation**: Clean technical documentation without emojis.

## [2.1.0] - 2026-08-03

### Added
- Initial cross-platform release for Linux (Ubuntu 24.04 / Debian / Arch) and Windows (10 / 11).
- Support for `systemd-resolved` DNS configuration.
- Machine code gate patching for x64 and ARM64 architectures.
