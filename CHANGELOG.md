# Changelog

All notable changes to the Antigravity CLI Unlocker project will be documented in this file.

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
