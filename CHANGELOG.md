# Changelog

All notable changes to the Antigravity CLI Unlocker project will be documented in this file.

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
