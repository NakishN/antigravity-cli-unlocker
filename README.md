# Antigravity CLI Unlocker

Antigravity CLI Unlocker provides regional unlock and DNS routing for **Google Antigravity CLI (`agy`)**, **Antigravity IDE**, and **Antigravity 2.0** on Linux and Windows platforms without requiring a VPN.

---

## Overview

In restricted regions, direct connections to Google Generative AI endpoints (`generativelanguage.googleapis.com`) and authentication gateways are restricted at the edge network level. Antigravity CLI Unlocker resolves this by:

1. **Binary Gate Patching**: Removing internal regional eligibility checks in the compiled `agy` / `agy.exe` binary (x64 and ARM64).
2. **System DNS Routing**: Routing Google API hostnames through Smart DNS gateways (`111.88.96.50` / `111.88.96.51`).

---

## Features at a Glance

| Feature | Antigravity CLI Unlocker |
| :--- | :--- |
| **Supported Platforms** | Ubuntu 24.04, Debian, Arch Linux, Fedora, Windows 10, Windows 11 |
| **Target Surfaces** | Antigravity CLI (`agy`), Antigravity IDE, Antigravity 2.0 |
| **Requirements** | No VPN required |
| **Safety** | Automated binary backups before patching, one-command rollback (`--restore`) |

---

## Installation & Setup

### Linux (Ubuntu / Debian / Arch)

Run the installation script:

```bash
git clone https://github.com/NakishN/antigravity-cli-unlocker.git
cd antigravity-cli-unlocker
chmod +x antigravity_unlock_linux.sh
./antigravity_unlock_linux.sh
```

#### Automated Operations:
- Locates the `agy` binary (`~/.local/bin/agy` or `/usr/local/bin/agy`).
- Creates a backup at `~/.local/share/antigravity-unlocker/agy.original.bak`.
- Applies machine code patches for x64 and ARM64 eligibility gates.
- Configures `systemd-resolved` (`/etc/systemd/resolved.conf.d/antigravity-unlock.conf`) to handle DNS resolution for Google API endpoints.

---

### Windows (10 / 11)

#### Method 1: Batch Launcher (Recommended)
1. Download or clone the repository.
2. Right-click **`antigravity_unlock_windows.bat`** and select **Run as administrator**.

#### Method 2: PowerShell (Administrator)
Open PowerShell as Administrator and run:

```powershell
Set-ExecutionPolicy Unrestricted -Scope Process -Force
.\antigravity_unlock_windows.ps1
```

---

## Rollback & Uninstallation

To restore the original binary and remove system DNS configurations:

### Linux
```bash
./antigravity_unlock_linux.sh --restore
```

### Windows
```powershell
.\antigravity_unlock_windows.ps1 -Restore
```

---

## Technical Integration & Compatibility

### Antigravity IDE & Antigravity 2.0
System-level DNS configuration (`systemd-resolved` on Linux or Network Adapter DNS on Windows) automatically applies to all Electron and Chromium network contexts used by Antigravity IDE and Antigravity 2.0. Consequently, all surfaces function seamlessly without additional configuration.

### Post-Update Re-application
When updating `agy` via `agy update`, Google replaces the binary. Run the unlock script again after any updates to re-apply the machine code patch.

---

## Support & Troubleshooting

If you encounter issues during installation or execution:

> [!NOTE]
> Please submit an issue report at [GitHub Issues](https://github.com/NakishN/antigravity-cli-unlocker/issues).

When reporting an issue, include:
- Operating System version (`lsb_release -a` or `winver`)
- Antigravity CLI version (`agy --version`)
- Complete console output log

---

## License

This project is licensed under the [MIT License](LICENSE).
