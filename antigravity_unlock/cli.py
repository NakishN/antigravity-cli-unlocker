"""
CLI Interface for Antigravity CLI Unlocker.
"""

import sys
import os
import shutil
import argparse

from antigravity_unlock import __version__
from antigravity_unlock.discovery import find_agy_binaries, get_primary_agy
from antigravity_unlock.patcher import (
    classify_binary,
    compute_sha256,
    get_backup_info,
    get_backup_path,
    list_pattern_names,
    patch_binary,
    restore_binary,
    unpatch_binary,
)
from antigravity_unlock.runner import run_wrapped_command
from antigravity_unlock.config import (
    DEFAULT_PINNED_VERSION,
    DEFAULT_STRATEGY,
    STRATEGY_AUTO,
    STRATEGY_IN_PLACE,
    STRATEGY_PIN,
    get_config_path,
    load_config,
    migrate_config,
    save_config,
)
from antigravity_unlock.egress import (
    PRESETS,
    STATUS_OK,
    STATUS_PROXY_UNREACHABLE,
    STATUS_REGION_BLOCKED,
    build_child_env,
    classify_agy,
    describe_route,
    format_results,
    parse_route,
    preset_hint,
    proxy_var_is_isolated,
    resolve_spec,
    route_egress_geo,
    geo_country,
    routes_from_config,
    select_route,
    status_text,
    active_route as egress_active_route,
)
from antigravity_unlock.model import (
    ModelSettingsError,
    RU_MODEL_IDS,
    backup_model,
    choose_ru_model,
    default_model,
    get_backup_path as get_model_backup_path,
    get_settings_path as get_agy_settings_path,
    is_gemini_model,
    resolve_model_choice,
    restore_default_model,
    set_default_model,
)
from antigravity_unlock.dnspin import (
    PIN_HOSTS,
    format_status,
    parse_hosts_pin,
    pin_ips,
    remove_hosts_pin,
    resolve_pin,
    start_proxy as start_dnspin_proxy,
    sync_hosts_pin,
    write_hosts_pin,
)
from antigravity_unlock.dnspin_timer import (
    DEFAULT_INTERVAL_SECONDS,
    SYNC_ARGS,
    autopin_status,
    install_autopin,
    remove_autopin,
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
║   Cross-Platform Patcher, Doctor & Guardian          ║
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
        fallback = "enabled" if cfg.get("allow_pin_fallback") else "disabled"
        strat_desc = f"Auto: In-place, pinned downgrade {fallback}"
    elif strat == STRATEGY_IN_PLACE:
        strat_desc = "In-place: Patch installed binary on the spot"
    else:
        strat_desc = "Pin: Enforce rollback and lock to pinned version"

    print(f"  Active Strategy: {strat} ({strat_desc})")
    print(f"  Pinned Version:  {cfg.get('pinned_version', DEFAULT_PINNED_VERSION)}")
    print(f"  Auto-Patch:      {cfg.get('auto_patch', True)}")
    print(f"  Optional Patches:{'on' if cfg.get('include_optional') else 'off'}")
    print(f"  Pinned Backup:   {'Present (' + pinned_bak + ')' if pinned_bak and os.path.exists(pinned_bak) else 'Not initialized'}")

    if primary and os.path.isfile(primary):
        state, detail = classify_binary(primary)
        label = {
            "patched": "PATCHED",
            "unpatched": "UNPATCHED",
            "foreign": "NOT RECOGNISED",
        }.get(state, state.upper())
        print("\n Patch State:")
        print(f"  {label}: {detail}")
        if state == "foreign":
            print("  -> run 'antigravity-unlock doctor' for a layered report")

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

    print("\n No-VPN DNS Pin (dnspin):")
    print(f"  Enabled:  {'Yes' if cfg.get('dnspin_enabled') else 'No'}")
    print("  Relays:   antigravity-unlock dnspin status")
    auto = autopin_status()
    auto_state = "not installed"
    if auto["installed"]:
        auto_state = "active" if auto["active"] else f"installed but {auto['detail'] or 'inactive'}"
        if auto.get("interval"):
            auto_state += f", every {auto['interval']}s"
    print(f"  Auto-refresh: {auto_state}")

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


# --------------------------------------------------------------------------
# model: the zero-cost fix for a blocked region
# --------------------------------------------------------------------------

MODEL_PROBE_PROMPT = "Reply with exactly: MODEL_OK"
MODEL_PROBE_TIMEOUT = 120


def model_status_cmd():
    path = get_agy_settings_path()
    print(f"  Settings: {path}")
    try:
        current = default_model(path)
    except ModelSettingsError as e:
        print(f"  Error: {e}", file=sys.stderr)
        return 1

    backup = backup_model(path)
    print(f"  Default:  {current or '(not set - agy decides)'}")
    print(f"  Backup:   {get_model_backup_path(path) if backup else 'none'}")
    if backup:
        print(f"            (original model: {backup!r})")

    if is_gemini_model(current):
        print("")
        print("  Gemini models are refused server-side from a blocked region")
        print("  (RU/BY/IR/CU/KP/SY/CR) with HTTP 400 'User location is not")
        print("  supported'.  claude-* and gpt-oss-* answered from a Russian IP")
        print("  with no VPN at all (measured 2026-10-27).")
        print("  Cheapest fix:  antigravity-unlock model ru")
    elif current:
        print("")
        print("  This is a non-Gemini model.  Measured working from a Russian IP")
        print("  with no VPN: claude-sonnet-4-6, claude-opus-4-6-thinking,")
        print("  gpt-oss-120b-medium.")
    return 0


def _model_live_probe(agy_path, model_id, timeout=MODEL_PROBE_TIMEOUT):
    """Run one real call with *model_id*.  Returns ``(status, output)``."""
    import subprocess

    route = egress_active_route(load_config(), agy_path=agy_path)
    env = build_child_env(route, agy_path=agy_path) if route else None
    cmd = [
        agy_path, "-p", MODEL_PROBE_PROMPT,
        "--model", model_id,
        "--print-timeout", f"{int(timeout)}s",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env,
            timeout=timeout + 30, check=False,
        )
    except subprocess.TimeoutExpired:
        return "timeout", f"no answer within {int(timeout)}s"
    except Exception as e:  # noqa: BLE001 - report, do not crash the command
        return "error", str(e)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    status, _detail = classify_agy(out, proc.returncode)
    return status, out


def model_cmd(sub, model=None, verify=True):
    path = get_agy_settings_path()
    agy_path = get_primary_agy()
    print_banner()

    if sub == "restore":
        try:
            ok, msg = restore_default_model(path)
        except ModelSettingsError as e:
            print(f"  Error: {e}", file=sys.stderr)
            return 1
        print(f"  {'OK' if ok else 'ERROR'}: {msg}")
        return 0 if ok else 1

    if sub == "status":
        return model_status_cmd()

    if sub == "ru":
        try:
            model_id, display = choose_ru_model(agy_path, preferred=model)
        except ModelSettingsError as e:
            print(f"  Error: {e}", file=sys.stderr)
            return 1
        why = " (the default; Gemini is refused from a blocked region)" if not model else ""
        print(f"  Chosen: {display}  [{model_id}]{why}")
    else:  # set
        try:
            model_id, display = resolve_model_choice(model, agy_path=agy_path)
        except ModelSettingsError as e:
            print(f"  Error: {e}", file=sys.stderr)
            return 1
        print(f"  Chosen: {display}  [{model_id}]")
        if is_gemini_model(display):
            print("  Warning: this is a Gemini model.  From a blocked region Google")
            print("  refuses it server-side even with a patched binary.")

    try:
        ok, msg = set_default_model(display, path=path)
    except ModelSettingsError as e:
        print(f"  Error: {e}", file=sys.stderr)
        return 1
    print(f"  {'OK' if ok else 'ERROR'}: {msg}")
    if not ok:
        return 1

    if not verify:
        return 0
    if not agy_path:
        print("  Verification skipped: agy binary not found.")
        return 0

    print(f"\n  Verifying with one real call ({model_id})...")
    status, out = _model_live_probe(agy_path, model_id)
    snippet = " / ".join(out.splitlines()[-2:])[:160]
    if status == STATUS_OK:
        print(f"  OK: agy answered end-to-end: {snippet!r}")
        return 0
    if status == STATUS_REGION_BLOCKED:
        print("  FAILED: Google still refused this model's region:")
        print(f"    {out[:300]}")
        print("  The setting was applied, but this model is gated too. Try another")
        print("  non-Gemini model:  antigravity-unlock model set <id>")
        return 1
    if status == STATUS_PROXY_UNREACHABLE:
        print(f"  WARNING: the configured exit is down, so nothing could be verified:")
        print(f"    {out[:300]}")
        print("  The model setting is saved and takes effect on the next agy start.")
        return 0
    print(f"  WARNING: setting saved, but the probe was inconclusive ({status}):")
    print(f"    {snippet or '(no output)'}")
    print("  This is often quota (429) rather than a regional refusal. Start agy and")
    print("  check the model shown in the TUI.")
    return 0


# --------------------------------------------------------------------------
# dnspin: no-VPN egress via public unblock-DNS relays
# --------------------------------------------------------------------------

DNSPIN_PROBE_PROMPT = "Reply with exactly: DNSPIN_OK"
DNSPIN_PROBE_TIMEOUT = 120


def _dnspin_chosen(proxy):
    return pin_ips(proxy.status) if proxy.status else dict(proxy.pinned)


def dnspin_status_cmd():
    print("  Querying geohide/comss/dns-ai and probing the relays...")
    status = resolve_pin()
    print("")
    print(format_status(status))
    pin = parse_hosts_pin()
    if pin:
        entries = ", ".join(f"{host.split('.')[0]}={ips[0]}" for host, ips in pin.items() if ips)
        print(f"\n  /etc/hosts pin: {entries}")
    else:
        print("\n  /etc/hosts pin: none (bare agy uses the direct path)")
    auto = autopin_status()
    if auto["installed"]:
        state = "active" if auto["active"] else f"INACTIVE ({auto['detail']})"
        print(f"  /etc/hosts auto-refresh: {state}")
    else:
        print("  /etc/hosts auto-refresh: not installed "
              "(sudo antigravity-unlock dnspin autopin install)")
    if any(info.get("chosen") for info in status.values()):
        print("")
        print("  At least one relay is alive.  Enable it for the wrapper with:")
        print("    antigravity-unlock dnspin enable")
        print("  Make bare agy use it (needs sudo once):")
        print("    sudo antigravity-unlock dnspin pin-hosts")
        print("  Then measure a real model call with:")
        print("    antigravity-unlock dnspin test --model gemini-3.8-flash-low")
        return 0
    print("")
    print("  No live relay right now.  The public unblock-DNS providers may be")
    print("  down or may not substitute for your region.  Fallbacks:")
    print("    antigravity-unlock model ru          (Claude/GPT-OSS, no exit)")
    print("    antigravity-unlock egress ...        (your own VPS/proxy)")
    return 1


def dnspin_pin_hosts_cmd():
    print("  Resolving and probing public unblock-DNS relays...")
    status = resolve_pin()
    chosen = pin_ips(status)
    if not any(chosen.values()):
        print("  No live relay found; nothing to pin.", file=sys.stderr)
        return 1
    ok, msg = write_hosts_pin(chosen)
    print(f"  {'OK' if ok else 'ERROR'}: {msg}")
    if not ok:
        exe = shutil.which("antigravity-unlock")
        hint = f"sudo {exe} dnspin pin-hosts" if exe else "sudo antigravity-unlock dnspin pin-hosts"
        print(f"  Run: {hint}", file=sys.stderr)
        print("  (sudo may not see ~/.local/bin, so the full path in the hint matters.)",
              file=sys.stderr)
        return 1
    print("  Bare agy now resolves the three API hosts to the relays.")
    print("  Restart agy (or open a new terminal) and try Gemini.")
    print("  Refresh later with: sudo antigravity-unlock dnspin pin-hosts")
    print("  Or keep it fresh automatically: sudo antigravity-unlock dnspin autopin install")
    return 0


def dnspin_unpin_hosts_cmd():
    ok, msg = remove_hosts_pin()
    print(f"  {'OK' if ok else 'ERROR'}: {msg}")
    return 0 if ok else 1


def dnspin_sync_hosts_cmd(quiet=False):
    """Refresh the hosts pin from live relays; used by the autopin timer."""
    code, msg = sync_hosts_pin()
    if code != 0 and "need root" in msg:
        msg += " (or install the timer once: sudo antigravity-unlock dnspin autopin install)"
    if not quiet:
        print(f"  {'OK' if code == 0 else 'ERROR'}: {msg}")
    return 0 if code == 0 else 1


def dnspin_autopin_cmd(action, interval=None, cli_path=None):
    action = action or "status"

    if action == "install":
        if cli_path and not os.path.isfile(cli_path):
            print(f"  ERROR: --cli path does not exist: {cli_path}", file=sys.stderr)
            return 1
        command = [os.path.abspath(cli_path), *SYNC_ARGS] if cli_path else None
        ok, msg = install_autopin(
            DEFAULT_INTERVAL_SECONDS if interval is None else interval,
            command=command,
        )
        print(f"  {'OK' if ok else 'ERROR'}: {msg}")
        if ok:
            print("  The refresh runs as root on a timer; no sudo is needed later.")
            print("  Check it with: antigravity-unlock dnspin autopin status")
        return 0 if ok else 1

    if action in ("remove", "uninstall"):
        ok, msg = remove_autopin()
        print(f"  {'OK' if ok else 'ERROR'}: {msg}")
        return 0 if ok else 1

    status = autopin_status()
    print(f"  Platform:  {status['platform']}")
    print(f"  Installed: {'Yes' if status['installed'] else 'No'}")
    print(f"  Active:    {'Yes' if status['active'] else 'No'}")
    if status.get("interval"):
        minutes = status["interval"] / 60
        pretty = f"{minutes:g} min" if minutes >= 1 else f"{status['interval']}s"
        print(f"  Interval:  {status['interval']}s ({pretty})")
    if status.get("path"):
        print(f"  Path:      {status['path']}")
    if status.get("detail"):
        print(f"  Detail:    {status['detail']}")
    return 0 if status["installed"] and status["active"] else 1


def dnspin_test_cmd(model=None, timeout=DNSPIN_PROBE_TIMEOUT):
    import subprocess

    model = model or "gemini-3.8-flash-low"
    agy_path = get_primary_agy()
    if not agy_path:
        print("Error: agy binary not found.", file=sys.stderr)
        return 1

    print("  Resolving and probing public unblock-DNS relays...")
    try:
        proxy = start_dnspin_proxy()
    except Exception as e:  # noqa: BLE001
        print(f"Error: cannot start dnspin proxy: {e}", file=sys.stderr)
        return 1
    try:
        chosen = _dnspin_chosen(proxy)
        if not any(chosen.values()):
            print("  No live relay found; nothing to test.", file=sys.stderr)
            return 1
        for host, ips in chosen.items():
            if ips:
                print(f"  {host} -> {', '.join(ips[:2])}")
        route = {"label": "dnspin", "url": f"http://127.0.0.1:{proxy.port}"}
        env = build_child_env(route, agy_path=agy_path)
        print(f"\n  Running one real agy call ({model}) through the pin...")
        proc = subprocess.run(
            [agy_path, "-p", DNSPIN_PROBE_PROMPT, "--model", model,
             "--print-timeout", f"{int(timeout)}s"],
            capture_output=True, text=True, env=env, timeout=timeout + 30, check=False,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        status, _detail = classify_agy(out, proc.returncode)
        snippet = " / ".join(out.splitlines()[-2:])[:200]
        if status == STATUS_OK:
            print(f"  OK: {snippet!r}")
            print("\n  DNS pin works. Enable it for 'antigravity-unlock run':")
            print("    antigravity-unlock dnspin enable")
            return 0
        if status == STATUS_REGION_BLOCKED:
            print(f"  REGION-BLOCKED: the relay is not exiting in a supported country: {snippet!r}")
            print("  Try again later (the provider rotates relays), or use 'model ru' / egress.")
            return 1
        print(f"  Inconclusive ({status}): {snippet or '(no output)'}")
        print("  The pin is live but the model call did not complete; check quota/sign-in.")
        return 1
    except subprocess.TimeoutExpired:
        print("  Timeout: the relay or model call did not finish in time.", file=sys.stderr)
        return 1
    finally:
        proxy.stop()


def dnspin_run_cmd(agy_args, timeout=None):
    import subprocess

    agy_path = get_primary_agy()
    if not agy_path:
        print("Error: agy binary not found.", file=sys.stderr)
        return 1
    print("  Resolving and probing public unblock-DNS relays...", file=sys.stderr)
    proxy = start_dnspin_proxy()
    try:
        chosen = _dnspin_chosen(proxy)
        if not any(chosen.values()):
            print("  No live relay found; running agy without the pin.", file=sys.stderr)
            return run_wrapped_command(agy_args)
        route = {"label": "dnspin", "url": f"http://127.0.0.1:{proxy.port}"}
        env = build_child_env(route, agy_path=agy_path)
        print("  Egress: dnspin -> " + ", ".join(
            f"{host.split('.')[0]}={ips[0]}" for host, ips in chosen.items() if ips
        ), file=sys.stderr)
        return subprocess.run([agy_path] + list(agy_args), env=env).returncode
    except KeyboardInterrupt:
        return 130
    finally:
        proxy.stop()


def dnspin_serve_cmd(port=0, refresh=300):
    import time

    proxy = start_dnspin_proxy(port=port, refresh_seconds=refresh)
    chosen = _dnspin_chosen(proxy)
    print(f"  dnspin proxy: http://127.0.0.1:{proxy.port}")
    for host, ips in chosen.items():
        print(f"  {host} -> {', '.join(ips[:2]) if ips else '(direct fallback)'}")
    print("  Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        proxy.stop()
    return 0


def dnspin_set_enabled(enabled):
    cfg = load_config()
    cfg["dnspin_enabled"] = bool(enabled)
    path = save_config(cfg)
    if enabled:
        print("  dnspin ENABLED. 'antigravity-unlock run' will resolve the public")
        print("  relays and route only the three Google API hosts through them.")
        print("  Verify with: antigravity-unlock dnspin test --model gemini-3.8-flash-low")
        print("  Disable with: antigravity-unlock dnspin disable")
    else:
        print("  dnspin DISABLED.")
    print(f"  Saved to {path}")
    return 0


# --------------------------------------------------------------------------
# egress: routing agy out through a supported region
# --------------------------------------------------------------------------

def _entry_label(entry):
    return entry.get("label") if isinstance(entry, dict) else entry


def _entry_url(entry):
    return entry.get("url") if isinstance(entry, dict) else entry


def egress_status_cmd():
    cfg = load_config()
    routes = routes_from_config(cfg)
    active = egress_active_route(cfg)

    print(f"  Routing:  {'ENABLED' if cfg.get('egress_enabled') else 'disabled'}")
    print(f"  Config:   {get_config_path()}")
    print(f"  Routes:   {len(routes)}")
    for route in routes:
        selected = active is not None and route["label"] == active["label"]
        print(f"    {'*' if selected else ' '} {describe_route(route)}"
              f"{'   <- selected' if selected else ''}")
    if not routes:
        print("    (none)")
    if cfg.get("egress_enabled") and routes and active is None:
        print("  Selected: none - the wrapper falls back to the first route")

    print("")
    print("  The binary patch clears the client-side eligibility gate.  Google also")
    print("  refuses the request's source IP server-side ('User location is not")
    print("  supported for the API use'), and that text is not in the binary, so no")
    print("  patch can remove it - only an exit in a supported region can.")
    return 0


def egress_presets_cmd():
    if not PRESETS:
        print("  (no presets)")
        return 0
    for name in sorted(PRESETS):
        entry = PRESETS[name]
        print(f"  {name}")
        print(f"    {entry['url']}")
        for line in (entry.get("hint") or "").splitlines():
            print(f"    {line}")
        print(f"    add it with: antigravity-unlock egress add {name}")
        print("")
    return 0


def _egress_add_entry(cfg, spec, label=None):
    """Validate *spec* and append it to ``cfg['egress_routes']``."""
    try:
        url, resolved = resolve_spec(spec)
    except ValueError as e:
        return False, str(e)
    if label:
        resolved = label

    route, err = parse_route(url, label=resolved)
    if route is None:
        return False, err

    routes = cfg.setdefault("egress_routes", [])
    for existing in routes:
        if _entry_url(existing) == url:
            if isinstance(existing, dict) and existing.get("label") != resolved:
                existing["label"] = resolved
                return True, f"already present, relabelled to {resolved!r}"
            return True, f"{describe_route(route)} is already configured"
        if isinstance(existing, dict) and existing.get("label") == resolved:
            existing["url"] = url
            return True, f"route {resolved!r} now points at {url}"

    routes.append({"label": resolved, "url": url})
    return True, f"added {describe_route(route)}"


def egress_add_cmd(spec, label=None):
    if spec is None:
        print("  Nothing to add.  Presets:")
        for name in sorted(PRESETS):
            print(f"    antigravity-unlock egress add {name}")
        print("  Or any proxy URL:")
        print("    antigravity-unlock egress add socks5h://host:1080")
        print("    antigravity-unlock egress add https://user:pass@host:8443")
        return 1

    cfg = load_config()
    ok, msg = _egress_add_entry(cfg, spec, label)
    if not ok:
        print(f"  Error: {msg}", file=sys.stderr)
        return 1

    path = save_config(cfg)
    print(f"  {msg}")

    hint = preset_hint(spec) if isinstance(spec, str) else None
    if hint:
        print("")
        for line in hint.splitlines():
            print(f"  {line}")

    print(f"\n  Saved to {path}")
    if cfg.get("egress_enabled"):
        print("  Measure it:      antigravity-unlock egress test")
    else:
        print("  Routing is still off: antigravity-unlock egress enable")
    return 0


def egress_remove_cmd(spec):
    cfg = load_config()
    kept, removed = [], None
    for entry in cfg.get("egress_routes") or []:
        if removed is None and spec in (_entry_label(entry), _entry_url(entry)):
            removed = entry
            continue
        kept.append(entry)

    if removed is None:
        print(f"  Error: no route matching {spec!r}.", file=sys.stderr)
        for route in routes_from_config(cfg):
            print(f"    {route['label']}", file=sys.stderr)
        return 1

    cfg["egress_routes"] = kept
    if cfg.get("egress_active") == _entry_label(removed):
        cfg["egress_active"] = ""
    save_config(cfg)

    print(f"  Removed {_entry_label(removed)}")
    if kept:
        print("  Still configured:")
        for route in routes_from_config(cfg):
            print(f"    {describe_route(route)}")
        print("  Re-measure:  antigravity-unlock egress test")
    else:
        print("  No routes left; agy will go out direct.")
    return 0


def egress_select_cmd(spec):
    cfg = load_config()
    match = None
    for route in routes_from_config(cfg):
        if spec in (route["label"], route["url"]):
            match = route
            break

    if match is None:
        print(f"  Error: no route matching {spec!r}.", file=sys.stderr)
        for route in routes_from_config(cfg):
            print(f"    {route['label']}", file=sys.stderr)
        return 1

    cfg["egress_active"] = match["label"]
    save_config(cfg)
    print(f"  Selected {describe_route(match)}")
    if not cfg.get("egress_enabled"):
        print("  Routing is disabled:  antigravity-unlock egress enable")
    print("  This did not measure anything - 'egress test' proves a route works.")
    return 0


def _egress_set_enabled(enabled):
    cfg = load_config()
    cfg["egress_enabled"] = bool(enabled)
    save_config(cfg)

    if not enabled:
        print("  Routing disabled.  agy goes out direct again.")
        print("  Routes are kept; 'egress enable' turns them back on.")
        return 0

    routes = routes_from_config(cfg)
    if not routes:
        print("  Routing enabled, but no routes are configured - agy will still go")
        print("  out direct.  Add one:  antigravity-unlock egress add warp")
        return 1

    active = egress_active_route(cfg)
    if active is None:
        print("  Routing enabled.  No route is selected yet, so the wrapper uses the")
        print("  first one.  Measure them:  antigravity-unlock egress test")
    else:
        print(f"  Routing enabled through {describe_route(active)}")
    return 0


def egress_test_cmd(model=None, timeout=None, preflight=True):
    cfg = load_config()
    routes = routes_from_config(cfg)
    if not routes:
        print("  No routes configured.", file=sys.stderr)
        print("  Add one first:  antigravity-unlock egress add warp", file=sys.stderr)
        return 1

    agy_path = get_primary_agy()
    if not agy_path:
        print("  Error: agy binary not found.", file=sys.stderr)
        return 1

    probe_timeout = int(timeout or cfg.get("egress_probe_timeout") or 120)
    probe_model = model or cfg.get("egress_model") or None

    print(f"  agy:     {agy_path}")
    print(f"  routes:  {len(routes)}")
    print(f"  model:   {probe_model or 'agy default'}")
    print("  Each route that passes the TCP check costs one real model call.\n")

    def progress(route, status, detail):
        print(f"  {route['label'][:24]:<24} {status_text(status):<18} {detail}")

    winner, results = select_route(
        agy_path, routes, timeout=probe_timeout, model=probe_model,
        preflight=preflight, on_progress=progress,
    )

    if winner is None:
        print("\n  No route produced a model completion.  Nothing was selected.")
        statuses = {r["status"] for r in results}
        if statuses and statuses <= {"region_blocked"}:
            print("  Every exit is still in a blocked region - the proxy is up, but it")
            print("  is not leaving the country.  Check the VPN/WARP node you are on.")
            print("  Gemini will stay refused, but you can still work with no exit at all:")
            print("    antigravity-unlock model ru   (switch the default to Claude)")
        elif statuses and statuses <= {"unreachable", "proxy_unreachable"}:
            print("  Nothing was listening on any route.  Start the proxy or VPN first.")
        else:
            print("  Detail per route is above; 'antigravity-unlock doctor' gives the")
            print("  full picture including the binary patch and sign-in state.")

        # A failed measurement does not clear a previous selection: the exit may
        # be down for a minute and wiping it would silently drop the user back
        # to a guaranteed region 400.  Say what is still armed instead.
        if cfg.get("egress_enabled") and cfg.get("egress_active"):
            print(f"\n  Routing is still ENABLED and pointed at {cfg['egress_active']}, so")
            print("  'antigravity-unlock run' keeps failing until that exit is back.")
            print("  To go direct meanwhile:  antigravity-unlock egress disable")
        return 1

    cfg["egress_active"] = winner["label"]
    cfg["egress_enabled"] = True
    save_config(cfg)

    print(f"\n  Selected: {describe_route(winner)}")
    geo = route_egress_geo(winner, timeout=10.0)
    country = geo_country(geo)
    if country:
        where = (geo.get("city") or geo.get("region") or "")
        print(f"  Exit:     {country}" + (f" ({where})" if where else ""))
    else:
        print("  Exit:     unknown (the geo services did not answer through it)")
    print("\n  Routing enabled.  'antigravity-unlock run' now uses this exit.")
    return 0


def egress_hook_cmd(sub):
    """Shell-profile integration, so a bare ``agy`` uses the exit too."""
    from antigravity_unlock import shellhook

    agy_path = get_primary_agy()
    cfg = load_config()
    routes = routes_from_config(cfg)
    route = egress_active_route(cfg, agy_path=agy_path) or (routes[0] if routes else None)

    if sub == "install":
        if route is None:
            print("  No route configured.", file=sys.stderr)
            print("  Add one first:  antigravity-unlock egress add warp", file=sys.stderr)
            return 1
        ok, msg = shellhook.install(route["url"], agy_path=agy_path)
        if ok:
            print(f"  {msg}")
            print("\n  The rename covers the lower-case literal only, so agy still")
            print("  honours an ambient HTTPS_PROXY - and Go reads that spelling")
            print("  first.  'egress hook status' reports a conflict if you have one.")
        else:
            print(f"  Error: {msg}", file=sys.stderr)
        return 0 if ok else 1

    if sub == "remove":
        ok, msg = shellhook.remove()
        print(f"  {msg}" if ok else f"  Error: {msg}", file=None if ok else sys.stderr)
        return 0 if ok else 1

    path = shellhook.profile_path()
    print(f"  Shell:      {os.environ.get('SHELL') or '?'}")
    print(f"  Profile:    {path or 'unsupported (add the export line by hand)'}")
    installed = shellhook.current_url(path) if path else None
    print(f"  Installed:  {installed or '(no managed block)'}")
    print(f"  Route:      {describe_route(route) if route else '(none configured)'}")
    if installed and route and installed != route["url"]:
        print("  NOTE: the profile and the selected route disagree; re-run")
        print("        'egress hook install' to refresh the block.")

    if agy_path:
        if proxy_var_is_isolated(agy_path):
            print("  Patch:      proxy_var_isolation applied - agy reads AG_LS_PROXY")
        else:
            print("  Patch:      proxy_var_isolation NOT applied - agy ignores")
            print("              AG_LS_PROXY entirely.  Fix with:")
            print("                antigravity-unlock patch --include-optional")

    conflict = shellhook.ambient_proxy_conflict()
    if conflict:
        print(f"  WARNING:    ambient {conflict[0]}={conflict[1]} outranks AG_LS_PROXY")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=f"Antigravity CLI Unlocker v{__version__} - Bypass regional restrictions & manage patch strategy."
    )
    parser.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default=None,
        help="Patch strategy: 'in_place' (default: patch the installed agy), "
             "'auto' (in-place, optional downgrade to a pinned build), "
             "'pin' (lock to the pinned version)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Patch agy if needed, then run it")
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
    patch_parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Also apply opt-in patterns (build-specific machine-code gates, https_proxy rename)",
    )
    patch_parser.add_argument(
        "--only", action="append", metavar="PATTERN", default=None,
        help="Restrict the run to these pattern names (repeatable). Naming an "
             "optional pattern here is itself the opt-in, so "
             "'--only proxy_var_isolation' applies just that length-preserving "
             "string rename and none of the machine-code patterns.",
    )

    # Command: doctor
    doctor_parser = subparsers.add_parser(
        "doctor", help="Layered diagnosis: binary, config, hosts pin, egress, endpoint, live agy run"
    )
    doctor_parser.add_argument("--no-network", action="store_true", help="Skip egress and endpoint probes")
    doctor_parser.add_argument(
        "--no-functional", action="store_true",
        help="Skip the live 'agy -p' run (it costs one model call)",
    )
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # Command: restore
    subparsers.add_parser("restore", help="Restore original agy binary from backup")

    # Command: unpatch
    unpatch_parser = subparsers.add_parser(
        "unpatch",
        help="Reverse the patch in place - no backup needed, unlike 'restore'",
    )
    unpatch_parser.add_argument("--dry-run", action="store_true", help="Show what would be reverted")
    unpatch_parser.add_argument(
        "--include-optional", action="store_true",
        help="Also revert opt-in patterns (machine-code gates, https_proxy rename)",
    )

    # Command: status
    subparsers.add_parser("status", help="Show system agy binaries, patch, pin, and autostart status")

    # Command: model
    model_parser = subparsers.add_parser(
        "model",
        help="Manage agy's default model - in a blocked region non-Gemini models "
             "work with no VPN at all",
    )
    model_sub = model_parser.add_subparsers(dest="model_subcommand", help="Model actions")
    model_sub.add_parser("status", help="Show the current default model and the backup")
    model_set = model_sub.add_parser("set", help="Set the default model by agy id or display name")
    model_set.add_argument("model", help="Model id (claude-sonnet-4-6) or display name")
    model_ru = model_sub.add_parser(
        "ru",
        help="Pick a non-Gemini model that works from a blocked region "
             "(default: claude-sonnet-4-6)",
    )
    model_ru.add_argument("--model", default=None, help="Override the chosen model id")
    model_ru.add_argument(
        "--no-verify", action="store_true",
        help="Do not spend one model call proving the new default answers",
    )
    model_sub.add_parser("restore", help="Restore the settings file saved before the first change")

    # Command: dnspin
    dnspin_parser = subparsers.add_parser(
        "dnspin",
        help="No-VPN egress: pin the three Google API hosts to public unblock-DNS relays",
    )
    dnspin_sub = dnspin_parser.add_subparsers(dest="dnspin_subcommand", help="DNS-pin actions")
    dnspin_sub.add_parser("status", help="Resolve and probe the public relays")
    dnspin_test = dnspin_sub.add_parser("test", help="Run one real model call through the pin")
    dnspin_test.add_argument("--model", default=None,
                             help="Model for the probe (default: gemini-3.8-flash-low)")
    dnspin_run = dnspin_sub.add_parser("run", help="Run agy wrapped in the DNS-pin proxy")
    dnspin_run.add_argument("agy_args", nargs=argparse.REMAINDER,
                            help="Arguments passed directly to agy")
    dnspin_serve = dnspin_sub.add_parser("serve", help="Run the local DNS-pin proxy in the foreground")
    dnspin_serve.add_argument("--port", type=int, default=0,
                              help="Listen port (default: ephemeral)")
    dnspin_serve.add_argument("--refresh", type=int, default=300,
                              help="Re-resolve the relays every N seconds (default: 300)")
    dnspin_sub.add_parser("enable", help="Use the pin in 'antigravity-unlock run'")
    dnspin_sub.add_parser("disable", help="Stop using the pin")
    dnspin_sub.add_parser(
        "pin-hosts",
        help="Write relay IPs to /etc/hosts so a bare agy uses them (needs sudo)",
    )
    dnspin_sub.add_parser(
        "unpin-hosts",
        help="Remove the dnspin block from /etc/hosts (needs sudo)",
    )
    dnspin_auto = dnspin_sub.add_parser(
        "autopin",
        help="Keep the /etc/hosts pin fresh with a root timer",
    )
    dnspin_auto_sub = dnspin_auto.add_subparsers(
        dest="autopin_subcommand", help="Autopin actions"
    )
    auto_install = dnspin_auto_sub.add_parser(
        "install", help="Install and start the refresh timer (needs sudo)"
    )
    auto_install.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
        help=f"Refresh interval in seconds (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    auto_install.add_argument(
        "--cli", default=None,
        help="Path to the antigravity-unlock executable for the timer "
             "(needed when running from a temporary AppImage mount)",
    )
    dnspin_auto_sub.add_parser("remove", help="Disable and remove the refresh timer (needs sudo)")
    dnspin_auto_sub.add_parser("status", help="Show whether the refresh timer is installed")
    dnspin_sub.add_parser(
        "sync-hosts",
        help="Refresh /etc/hosts from live relays only if they changed "
             "(root; used by the timer)",
    )

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

    # Command: egress
    egress_parser = subparsers.add_parser(
        "egress",
        help="Route agy out through a supported region - the server-side gate the "
             "binary patch cannot clear",
    )
    eg_sub = egress_parser.add_subparsers(dest="egress_subcommand", help="Egress actions")
    eg_sub.add_parser("status", help="Show routes, the selected one, and whether routing is on")
    eg_sub.add_parser("presets", help="List named routes you can add without an address")

    eg_add = eg_sub.add_parser("add", help="Add a route: a preset name or a proxy URL")
    eg_add.add_argument(
        "spec", nargs="?", default=None,
        help="Preset name (e.g. 'warp') or a proxy URL such as socks5h://host:1080",
    )
    eg_add.add_argument("--label", default=None, help="Name for this route (default: the URL)")

    eg_rm = eg_sub.add_parser("remove", help="Remove a route by label or URL")
    eg_rm.add_argument("spec", help="Label or URL of the route to remove")

    eg_sel = eg_sub.add_parser("select", help="Pick the route the wrapper uses, without measuring it")
    eg_sel.add_argument("spec", help="Label or URL of the route to select")

    eg_test = eg_sub.add_parser(
        "test",
        help="Measure every route with one real model call each, then select the winner",
    )
    eg_test.add_argument("--model", default=None, help="Model for the probe (default: agy's own)")
    eg_test.add_argument("--timeout", type=int, default=None, help="Seconds per route (default 120)")
    eg_test.add_argument(
        "--no-preflight", action="store_true",
        help="Skip the TCP reachability check and probe every route with a model call",
    )

    eg_sub.add_parser("enable", help="Make the wrapper route agy through the selected exit")
    eg_sub.add_parser("disable", help="Stop routing; agy goes out direct again")

    eg_hook = eg_sub.add_parser(
        "hook",
        help="Make a bare 'agy' use the exit too, via AG_LS_PROXY in your shell profile",
    )
    hook_sub = eg_hook.add_subparsers(dest="egress_hook_subcommand", help="Hook actions")
    hook_sub.add_parser(
        "install",
        help="Write the managed block (requires the proxy_var_isolation patch)",
    )
    hook_sub.add_parser("remove", help="Delete the managed block and nothing else")
    hook_sub.add_parser("status", help="Show the block, the profile, and any conflicting ambient proxy")

    # Command: setup (legacy hosts-pin cleanup only - pinning was removed in 1.5.0)
    setup_parser = subparsers.add_parser(
        "setup", help="Remove /etc/hosts pins left behind by versions <=1.4.x (requires sudo)"
    )
    setup_sub = setup_parser.add_subparsers(dest="setup_subcommand", help="Setup actions")
    setup_sub.add_parser("apply", help="Removed in 1.5.0 - explains why and what to run instead")
    setup_sub.add_parser("remove", help="Delete leftover pin lines from /etc/hosts (requires root)")
    setup_sub.add_parser("status", help="Show leftover pin lines in /etc/hosts")

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

    # Bring a pre-1.5 config forward before anything reads it.  Most importantly
    # this clears a `strategy: pin` that predates an agy self-update: left alone,
    # the next guardian tick would replace a newer working agy with the stale
    # pinned build.
    try:
        _primary = get_primary_agy()
        _installed = get_agy_version(_primary) if _primary else None
        _changed, _cfg, _notes = migrate_config(installed_version=_installed)
        if _changed and _notes and not getattr(args, "json", False):
            for _n in _notes:
                if "strategy" in _n:
                    print(f"[config] {_n}")
    except Exception:
        pass

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
        include_optional = getattr(args, "include_optional", False) or load_config().get("include_optional", False)
        only = getattr(args, "only", None)
        if only:
            known = set(list_pattern_names())
            unknown = [name for name in only if name not in known]
            if unknown:
                # A typo here would otherwise apply nothing and still report
                # success, which is the worst outcome for an allowlist flag.
                print("Error: unknown pattern name(s): %s" % ", ".join(unknown), file=sys.stderr)
                print("Known patterns:", file=sys.stderr)
                for name in sorted(known):
                    print("  %s" % name, file=sys.stderr)
                sys.exit(2)
        success, msg, _ = patch_binary(
            agy_path,
            dry_run=getattr(args, "dry_run", False),
            force=getattr(args, "force", False),
            include_optional=include_optional,
            only=only,
        )
        print(f"Result: {msg}")
        state, detail = classify_binary(agy_path)
        print(f"State:  {state} ({detail})")
        if state == "foreign":
            print(
                "\nThis agy build is not recognised. It was left unmodified so that it can\n"
                "report its own error, rather than being handed back looking patched.\n"
                "Update antigravity-cli-unlocker, or add a signature for this build.",
                file=sys.stderr,
            )
        sys.exit(0 if success else 1)

    elif args.command == "doctor":
        import json as _json

        from antigravity_unlock.doctor import format_report, run_doctor

        overall, layers, meta = run_doctor(
            skip_network=getattr(args, "no_network", False),
            skip_functional=getattr(args, "no_functional", False),
        )
        if getattr(args, "json", False):
            print(_json.dumps(
                {"overall": overall, "checks": layers, "meta": meta},
                indent=2, default=str,
            ))
        else:
            print_banner()
            print(format_report(overall, layers, meta))
        sys.exit(0 if overall != "fail" else 1)

    elif args.command == "restore":
        print_banner()
        agy_path = get_primary_agy()
        if not agy_path:
            print("Error: agy binary not found.", file=sys.stderr)
            sys.exit(1)

        info = get_backup_info(agy_path)
        if info["stale"] and not getattr(args, "force", False):
            print(
                f"Refusing to restore: the backup is {info['backup_size']} bytes but the\n"
                f"installed agy is {info['installed_size']}. The backup belongs to an older\n"
                f"build, so restoring it would silently DOWNGRADE agy.\n"
                f"\n"
                f"  Backup:    {info['path']}\n"
                f"\n"
                f"To undo the patch without touching the version:\n"
                f"  antigravity-unlock unpatch\n"
                f"\n"
                f"To restore the older build anyway:\n"
                f"  antigravity-unlock restore --force",
                file=sys.stderr,
            )
            sys.exit(1)

        success, msg = restore_binary(agy_path)
        print(f"Result: {msg}")
        state, detail = classify_binary(agy_path)
        print(f"State:  {state} ({detail})")
        sys.exit(0 if success else 1)

    elif args.command == "unpatch":
        print_banner()
        agy_path = get_primary_agy()
        if not agy_path:
            print("Error: agy binary not found.", file=sys.stderr)
            sys.exit(1)
        include_optional = getattr(args, "include_optional", False) or load_config().get("include_optional", False)
        success, msg, _ = unpatch_binary(
            agy_path,
            dry_run=getattr(args, "dry_run", False),
            include_optional=include_optional,
        )
        print(f"Result: {msg}")
        state, detail = classify_binary(agy_path)
        print(f"State:  {state} ({detail})")
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

    elif args.command == "dnspin":
        sub = getattr(args, "dnspin_subcommand", None) or "status"
        if sub != "run":
            print_banner()
        if sub == "status":
            sys.exit(dnspin_status_cmd())
        elif sub == "test":
            sys.exit(dnspin_test_cmd(model=getattr(args, "model", None)))
        elif sub == "run":
            agy_args = list(getattr(args, "agy_args", []) or [])
            if agy_args and agy_args[0] == "--":
                agy_args = agy_args[1:]
            sys.exit(dnspin_run_cmd(agy_args))
        elif sub == "serve":
            sys.exit(dnspin_serve_cmd(
                port=getattr(args, "port", 0),
                refresh=getattr(args, "refresh", 300),
            ))
        elif sub == "enable":
            sys.exit(dnspin_set_enabled(True))
        elif sub == "disable":
            sys.exit(dnspin_set_enabled(False))
        elif sub == "pin-hosts":
            sys.exit(dnspin_pin_hosts_cmd())
        elif sub == "unpin-hosts":
            sys.exit(dnspin_unpin_hosts_cmd())
        elif sub == "autopin":
            sys.exit(dnspin_autopin_cmd(
                getattr(args, "autopin_subcommand", None) or "status",
                interval=getattr(args, "interval", None),
                cli_path=getattr(args, "cli", None),
            ))
        elif sub == "sync-hosts":
            sys.exit(dnspin_sync_hosts_cmd())
        else:
            sys.exit(dnspin_set_enabled(False))

    elif args.command == "model":
        sub = getattr(args, "model_subcommand", None) or "status"
        sys.exit(model_cmd(
            sub,
            model=getattr(args, "model", None),
            verify=not getattr(args, "no_verify", False),
        ))

    elif args.command == "egress":
        sub = getattr(args, "egress_subcommand", None) or "status"
        print_banner()
        if sub == "add":
            sys.exit(egress_add_cmd(getattr(args, "spec", None), getattr(args, "label", None)))
        elif sub == "remove":
            sys.exit(egress_remove_cmd(getattr(args, "spec", None)))
        elif sub == "select":
            sys.exit(egress_select_cmd(getattr(args, "spec", None)))
        elif sub == "test":
            sys.exit(egress_test_cmd(
                model=getattr(args, "model", None),
                timeout=getattr(args, "timeout", None),
                preflight=not getattr(args, "no_preflight", False),
            ))
        elif sub == "enable":
            sys.exit(_egress_set_enabled(True))
        elif sub == "disable":
            sys.exit(_egress_set_enabled(False))
        elif sub == "presets":
            sys.exit(egress_presets_cmd())
        elif sub == "hook":
            sys.exit(egress_hook_cmd(getattr(args, "egress_hook_subcommand", None) or "status"))
        else:
            sys.exit(egress_status_cmd())

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

    elif args.command == "setup":
        from antigravity_unlock.hosts_cleanup import find_pins, unpin

        sub = getattr(args, "setup_subcommand", None) or "status"
        print_banner()
        if sub == "apply":
            print(
                "  REFUSED: hosts pinning was removed in 1.5.0.\n"
                "\n"
                "  Pinning CloudCode to a third-party SNI proxy was never what unlocked\n"
                "  Antigravity - the eligibility gate is a client-side check over a\n"
                "  server-supplied protobuf field, and renaming that field is sufficient\n"
                "  (verified on agy 1.2.7 from a blocked-region IP with no proxy at all).\n"
                "  A pin only overrides whatever egress route you already have, and the\n"
                "  front end this used to point at no longer completes a TLS handshake.\n"
                "\n"
                "  To unlock:      antigravity-unlock patch\n"
                "  To diagnose:    antigravity-unlock doctor\n"
                "  To clean up an old pin:  sudo antigravity-unlock setup remove"
            )
            sys.exit(1)
        elif sub == "remove":
            try:
                removed, msg = unpin()
                print(f"  {'OK' if removed else 'NOOP'}: {msg}")
                sys.exit(0)
            except PermissionError as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                sys.exit(1)
        else:  # status
            pins = find_pins()
            print(f"  Pin lines in /etc/hosts: {len(pins)}")
            for lineno, line, marked in pins:
                origin = "marked block" if marked else "unmarked (older release)"
                print(f"    line {lineno}: {line}   [{origin}]")
            if pins:
                print("  These are leftovers from <=1.4.x and serve no purpose now.")
                print("  Run 'sudo antigravity-unlock setup remove' to delete them.")
            else:
                print("  Clean - agy resolves CloudCode normally.")
        sys.exit(0)

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
            ok, msg, _ = enforce_strategy(
                strategy=active_strat,
                include_optional=bool(cfg.get("include_optional", False)),
            )
            print(f"Result: {msg}")
            print("\nUsage tips:")
            print("  antigravity-unlock patch               (Patch the installed agy in place)")
            print("  antigravity-unlock doctor              (Layered diagnosis, ends with a live agy run)")
            print("  antigravity-unlock run -- <agy args>   (Patch if needed, then exec agy)")
            print("  antigravity-unlock autostart install   (Re-patch automatically after agy self-updates)")
            print("  antigravity-unlock egress add warp     (Add an exit in a supported region)")
            print("  antigravity-unlock egress test         (Measure routes with a real model call, select one)")
            print("  antigravity-unlock egress hook install (Make a bare 'agy' use that exit too)")
            print("  antigravity-unlock pin strategy in_place|auto|pin")
            print("  antigravity-unlock restore             (Restore original binary)")
            print("  sudo antigravity-unlock setup remove   (Delete /etc/hosts pins left by <=1.4.x)")


if __name__ == "__main__":
    main()
