"""
Binary Patcher Module.
Applies exact SHA-256 or wildcard byte-pattern modifications to agy executables safely.

The primary fix is a same-length literal rename (``ineligible`` -> ``inexigible``).
Same length means offsets, relocations and the ELF/PE layout are untouched, and
the revert is byte-exact.  Because the rename is applied to *every* occurrence,
the serialized protobuf descriptor and the matching Go struct tags stay
consistent with each other, so the JSON the client decodes no longer carries the
field the eligibility gate reads.

Patterns are tiered so a new agy build degrades gracefully instead of silently
reporting success:

``primary``     The rename everything else depends on.  If neither it nor its
                replacement is present, this is a build the patcher does not
                understand and the binary is left alone.
``best_effort`` Version-specific additions (machine-code gates).  Absence is
                normal on a new build and is never a failure.
``optional``    Off by default; opt in explicitly (e.g. the proxy-var rename,
                which only makes sense when this tool supplies the proxy).
"""

import os
import json
import shutil
import hashlib
import platform

# Outcome of a repatch attempt.  Mirrors the distinction the guardian depends
# on: "an update reverted us" must never be confused with "we do not recognise
# this build", because only the first one is safe to fix automatically.
OUTCOME_PATCHED = "patched"              # rename applied now
OUTCOME_ALREADY_PATCHED = "already"      # nothing to do
OUTCOME_SIGNATURE_MISSING = "foreign"    # unknown build - left untouched
OUTCOME_FAILED = "failed"                # transient I/O error - worth a retry

STATE_PATCHED = "patched"
STATE_UNPATCHED = "unpatched"
STATE_FOREIGN = "foreign"

# Streamed in 8 MiB chunks so inspecting a 220 MB binary does not need 220 MB
# of resident memory - the guardian polls this on every interval.
_SCAN_CHUNK = 8 * 1024 * 1024


def compute_sha256(filepath):
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_app_dir():
    """Returns application data directory for backups and logs."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    app_dir = os.path.join(base, "antigravity-unlocker")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

def load_versions_db():
    """Loads versions.json registry from package directory."""
    pkg_dir = os.path.dirname(__file__)
    v_path = os.path.join(pkg_dir, "versions.json")
    if os.path.exists(v_path):
        try:
            with open(v_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"versions": {}, "wildcard_patterns": []}

def get_backup_path(agy_path):
    """Generates backup path for a target binary."""
    app_dir = get_app_dir()
    filename = os.path.basename(agy_path) + ".original.bak"
    return os.path.join(app_dir, filename)

def _warn(agy_path, message):
    """Log a warning without importing logging at module import time."""
    import logging

    logging.getLogger("antigravity_unlocker").warning("%s: %s", agy_path, message)


def backup_binary(agy_path, dry_run=False):
    """Back up the *pristine* binary, refreshing a stale backup.

    Two invariants, both learned from a real bug:

    - **Pristine.** The backup must not carry the patch, or ``restore`` becomes a
      no-op. So an already-patched binary is never copied over a backup.
    - **Current.** The backup must match the installed build. The old code wrote
      only when the file was absent, so after an agy self-update the stored
      backup stayed at the *previous* version and ``restore`` silently downgraded
      agy - observed live: backup 1.1.27 / 210 MB against installed 1.2.7 / 224 MB.

    Returns ``(backup_path, created_or_refreshed)``.
    """
    backup_file = get_backup_path(agy_path)
    try:
        current_size = os.path.getsize(agy_path)
    except OSError:
        current_size = None

    if os.path.exists(backup_file):
        try:
            same_size = current_size is not None and os.path.getsize(backup_file) == current_size
        except OSError:
            return backup_file, False
        if same_size:
            return backup_file, False

        # Size differs: either the backup predates a self-update, or the
        # installed binary is already patched.  Only the first may be refreshed -
        # overwriting a pristine backup with a patched image would destroy the
        # only way back.
        try:
            state, _ = classify_binary(agy_path)
        except OSError:
            return backup_file, False
        if state != STATE_UNPATCHED:
            _warn(agy_path, f"backup does not match installed agy ('{state}'); left untouched")
            return backup_file, False

        if dry_run:
            return backup_file, True
        _warn(agy_path, "refreshing stale backup left over from an older agy")
        shutil.copy2(agy_path, backup_file)
        return backup_file, True

    try:
        state, _ = classify_binary(agy_path)
    except OSError:
        state = None
    if state == STATE_PATCHED:
        _warn(agy_path, "no pristine backup available: installed agy is already patched")
        return backup_file, False

    if not dry_run:
        shutil.copy2(agy_path, backup_file)
    return backup_file, True


def get_backup_info(agy_path):
    """Describe the restore point for *agy_path*, including whether it is stale.

    ``stale`` means restoring would not give back the installed build - the
    condition that silently downgrades agy after a self-update.
    """
    backup_file = get_backup_path(agy_path)
    info = {
        "path": backup_file,
        "exists": os.path.exists(backup_file),
        "backup_size": None,
        "installed_size": None,
        "stale": False,
    }
    try:
        info["installed_size"] = os.path.getsize(agy_path)
    except OSError:
        pass
    if info["exists"]:
        try:
            info["backup_size"] = os.path.getsize(backup_file)
        except OSError:
            info["exists"] = False
    if info["exists"] and info["installed_size"] is not None:
        info["stale"] = info["backup_size"] != info["installed_size"]
    return info


def restore_binary(agy_path):
    """Restores the original binary from backup."""
    backup_file = get_backup_path(agy_path)
    if os.path.exists(backup_file):
        shutil.copy2(backup_file, agy_path)
        return True, f"Restored {agy_path} from {backup_file}"
    return False, f"Backup file not found at {backup_file}"


def unpatch_binary(agy_path, dry_run=False, include_optional=False):
    """Reverse every rename in place, without depending on a backup.

    Each signature is a same-length literal swap, so the inverse is exact.  This
    is the restore path that still works after an agy self-update, when the
    stored backup belongs to an older build and restoring it would downgrade agy.

    Returns ``(success, message, sha256_after)``.
    """
    sha_before = compute_sha256(agy_path)
    with open(agy_path, "rb") as f:
        data = bytearray(f.read())

    vdb = load_versions_db()
    reverted = []
    for wp in vdb.get("wildcard_patterns", []):
        if _pattern_tier(wp) == "optional" and not include_optional:
            continue
        decoded = _pattern_bytes(wp)
        if decoded is None or not _pattern_applicable(wp):
            continue
        original, replacement = decoded
        count = data.count(replacement)
        if count > 0:
            data[:] = bytes(data).replace(replacement, original)
            reverted.append(f"{wp.get('name', 'pattern')} ({count}x)")

    if not reverted:
        state, detail = classify_binary(agy_path)
        return True, f"Nothing to revert ({state}: {detail})", sha_before

    if dry_run:
        return True, f"[DRY-RUN] Would revert: {', '.join(reverted)}", sha_before

    err = _write_atomic(agy_path, data)
    if err is not None:
        return False, f"Failed writing revert: {err}", sha_before

    return True, f"Reverted: {', '.join(reverted)}", compute_sha256(agy_path)

def _current_platform_tag():
    """Returns a tag like 'linux_x86_64' for platform-specific pattern filtering."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        machine = "x86_64"
    return f"{platform.system().lower()}_{machine}"


def _pattern_applicable(wp):
    """True if a wildcard pattern applies to the current platform.

    Patterns with no ``platform`` field are cross-platform (string literals
    such as the protobuf rename).  Patterns with a ``platform`` list are
    only applied when the current platform tag is in the list.
    """
    platforms = wp.get("platform")
    if not platforms:
        return True
    tag = _current_platform_tag()
    return tag in platforms


def _pattern_tier(wp):
    """Classify a wildcard pattern into primary / best_effort / optional / standard."""
    if wp.get("optional"):
        return "optional"
    if wp.get("best_effort"):
        return "best_effort"
    if wp.get("primary"):
        return "primary"
    return "standard"


def _pattern_bytes(wp):
    """Decode a pattern's search/replace pair, or None if it cannot preserve size.

    Every rename must be exactly the same length: that is what keeps the binary
    layout intact and makes the revert a pure byte swap.
    """
    try:
        original = bytes.fromhex(wp["pattern"])
        replacement = bytes.fromhex(wp["replacement"])
    except (KeyError, ValueError):
        return None
    if not original or len(original) != len(replacement):
        return None
    return original, replacement


def count_needles_stream(filepath, needles, chunk_size=_SCAN_CHUNK):
    """Count every needle in one streaming pass over *filepath*.

    Returns ``{needle: count}``.  Counting all needles in a single pass matters
    here: the target is a ~220 MB binary and the guardian polls it, so one read
    per needle would be ten full passes over the file.

    A suffix of ``max(len(needle)) - 1`` bytes is carried into the next chunk so
    a match straddling the boundary is still seen.  The carried suffix is part of
    both the previous and the current window, so its own match count is
    subtracted once; that keeps the invariant ``counts[n] == matches(bytes read
    so far)`` exactly.  Because the invariant already accounts for the whole
    file once the last block is read, nothing is added back at EOF - doing so
    double-counts every match sitting in the final suffix.  This is exact for
    needles that cannot overlap themselves (true of every literal here, e.g.
    ``ineligible`` has no border), which ``tests/test_patcher.py`` pins down at
    several chunk sizes including files smaller than the carry window.
    """
    needles = [n for n in needles if n]
    counts = dict.fromkeys(needles, 0)
    if not needles:
        return counts

    keep = max(len(n) for n in needles) - 1
    tail = b""
    with open(filepath, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            buf = tail + block
            for n in needles:
                counts[n] += buf.count(n) - tail.count(n)
            if keep and len(buf) > keep:
                tail = buf[len(buf) - keep:]
            elif keep:
                tail = buf
            else:
                tail = b""

    return counts


def inspect_binary(agy_path, include_optional=True):
    """Return a per-pattern census of *agy_path*.

    Result shape::

        {"size": int, "patterns": [{"name", "tier", "original_hits",
                                    "replacement_hits", "applies"}],
         "primary": {"name", "original_hits", "replacement_hits"} | None}

    One streaming pass, so this is cheap enough for the guardian to poll.
    """
    vdb = load_versions_db()
    size = os.path.getsize(agy_path)

    specs = []
    for wp in vdb.get("wildcard_patterns", []):
        tier = _pattern_tier(wp)
        if tier == "optional" and not include_optional:
            continue
        decoded = _pattern_bytes(wp)
        if decoded is None:
            continue
        if not _pattern_applicable(wp):
            specs.append((wp, tier, None, None))
            continue
        specs.append((wp, tier, decoded[0], decoded[1]))

    needles = {b for s in specs for b in (s[2], s[3]) if b}
    counts = count_needles_stream(agy_path, needles)

    rows = []
    primary = None
    for wp, tier, original, replacement in specs:
        applies = original is not None
        row = {
            "name": wp.get("name", "pattern"),
            "tier": tier,
            "applies": applies,
            "original_hits": counts.get(original, 0) if applies else 0,
            "replacement_hits": counts.get(replacement, 0) if applies else 0,
        }
        rows.append(row)
        if tier == "primary" and primary is None:
            primary = row

    return {"size": size, "patterns": rows, "primary": primary}


def classify_binary(agy_path):
    """Classify patch state without modifying anything.

    Returns ``(state, detail)`` where *state* is one of ``STATE_PATCHED``,
    ``STATE_UNPATCHED`` or ``STATE_FOREIGN``.

    ``STATE_FOREIGN`` means the primary signature is absent *and* its
    replacement is absent: this is not agy as we know it.  Leaving such a binary
    alone is deliberate - Antigravity then launches and shows its own error,
    which is the user's cue to update this patcher, rather than being handed a
    silently unmodified binary that appears to have been patched.
    """
    info = inspect_binary(agy_path, include_optional=False)
    primary = info.get("primary")
    if primary is None:
        return STATE_FOREIGN, "no primary pattern defined in versions.json"
    if primary["original_hits"] == 0 and primary["replacement_hits"] == 0:
        return STATE_FOREIGN, f"primary signature '{primary['name']}' absent"
    if primary["original_hits"] == 0:
        return STATE_PATCHED, f"{primary['name']} renamed ({primary['replacement_hits']}x)"
    return STATE_UNPATCHED, f"{primary['name']} present ({primary['original_hits']}x)"


def _write_atomic(agy_path, data):
    """Write *data* over *agy_path* via a sibling temp + rename."""
    tmp_path = agy_path + ".tmp_patch"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, os.stat(agy_path).st_mode)
        os.replace(tmp_path, agy_path)
        return None
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return e


def repatch_if_needed(agy_path, dry_run=False, include_optional=False):
    """Re-apply the patch to a binary that an agy self-update may have reverted.

    Unlike :func:`patch_binary` this never conflates "nothing to patch because
    the signature is gone" with "already patched" - that distinction is the
    whole point of the guardian.

    Returns ``(outcome, message)`` with *outcome* one of the ``OUTCOME_*``
    constants.
    """
    try:
        with open(agy_path, "rb") as f:
            data = bytearray(f.read())
    except OSError as e:
        return OUTCOME_FAILED, f"cannot read {agy_path}: {e}"

    applied, skipped, missing_best_effort = _apply_patterns(
        data, include_optional=include_optional
    )

    primary_state, _ = classify_binary(agy_path)
    if not applied:
        if primary_state == STATE_FOREIGN:
            return OUTCOME_SIGNATURE_MISSING, "primary signature absent - build not recognised, left untouched"
        if missing_best_effort:
            return OUTCOME_ALREADY_PATCHED, (
                "already patched (best-effort patterns absent: "
                + ", ".join(missing_best_effort) + ")"
            )
        return OUTCOME_ALREADY_PATCHED, "already patched"

    if dry_run:
        return OUTCOME_ALREADY_PATCHED, f"[DRY-RUN] would apply: {', '.join(applied)}"

    backup_binary(agy_path, dry_run=False)
    err = _write_atomic(agy_path, data)
    if err is not None:
        return OUTCOME_FAILED, f"failed writing patch: {err}"

    msg = "repatched: " + ", ".join(applied)
    if skipped:
        msg += f" (skipped platform-specific: {', '.join(skipped)})"
    return OUTCOME_PATCHED, msg


def _apply_patterns(data, include_optional=False, only=None):
    """Apply wildcard patterns to *data* in place.

    Returns ``(applied, skipped_platform, missing_best_effort)`` where *applied*
    holds human-readable ``"name (Nx)"`` strings.

    *only* is an allowlist of pattern names.  Naming an optional pattern there
    is itself the opt-in, so ``only=["proxy_var_isolation"]`` applies exactly
    that one string rename and none of the others.  That matters because
    ``--include-optional`` is all-or-nothing and the optional tier mixes two
    very different kinds of change: length-preserving string renames, which are
    safe on any build, and byte-exact machine-code rewrites whose offsets were
    taken from one specific build.  Applying the latter to a build agy has
    since self-updated to is how you corrupt a 220 MB binary.
    """
    vdb = load_versions_db()
    applied = []
    skipped = []
    missing_best_effort = []
    only = set(only) if only else None

    for wp in vdb.get("wildcard_patterns", []):
        name = wp.get("name", "pattern")
        tier = _pattern_tier(wp)
        if only is not None:
            if name not in only:
                continue
        elif tier == "optional" and not include_optional:
            continue

        decoded = _pattern_bytes(wp)
        if decoded is None:
            continue
        original, replacement = decoded

        if not _pattern_applicable(wp):
            skipped.append(name)
            continue

        count = data.count(original)
        if count > 0:
            data[:] = bytes(data).replace(original, replacement)
            applied.append(f"{name} ({count}x)")
        elif tier == "best_effort" and data.count(replacement) == 0:
            missing_best_effort.append(name)

    return applied, skipped, missing_best_effort


def list_pattern_names():
    """Every wildcard pattern name in the registry, for validating ``--only``.

    A typo in an allowlist would otherwise apply nothing at all and report
    success, which is the worst possible outcome for a flag like this.
    """
    vdb = load_versions_db()
    return [wp.get("name", "pattern") for wp in vdb.get("wildcard_patterns", [])]


def patch_binary(agy_path, dry_run=False, force=False, include_optional=False,
                 only=None):
    """
    Patches the agy binary.
    1. Check SHA-256 against versions.json for exact-offset patches
    2. Apply version-agnostic wildcard patterns (bare-literal renames)
    3. Atomically write the patched binary

    *only* restricts step 2 to the named patterns; see ``_apply_patterns``.

    Returns ``(success, message, sha256_after)``.  ``success`` is False only for
    a real failure: a build whose primary signature is absent reports True with
    an explicit "not recognised" message, because there is nothing to fix and
    the caller should not retry forever.
    """
    sha_orig = compute_sha256(agy_path)
    vdb = load_versions_db()

    with open(agy_path, "rb") as f:
        data = bytearray(f.read())

    applied_details = []

    # Exact-offset patches only apply to a byte-identical registered build.
    # Wildcard patterns are applied regardless: they are idempotent renames, so
    # running both is harmless, and a registered build whose offsets have drifted
    # still gets fixed by the literal renames.
    exact_match = None
    for vname, vinfo in vdb.get("versions", {}).items():
        if vinfo.get("sha256") == sha_orig:
            exact_match = vname
            for p in vinfo.get("patches", []):
                offset = p["offset"]
                orig_bytes = bytes.fromhex(p["original"])
                repl_bytes = bytes.fromhex(p["replacement"])
                if data[offset:offset + len(orig_bytes)] == orig_bytes:
                    data[offset:offset + len(orig_bytes)] = repl_bytes
                    applied_details.append(f"Exact offset {offset}: {vname}")
            break

    applied, skipped, missing_best_effort = _apply_patterns(
        data, include_optional=include_optional, only=only
    )
    applied_details.extend(applied)

    if not applied_details:
        state, detail = classify_binary(agy_path)
        if state == STATE_FOREIGN:
            return True, (
                f"Primary signature not found ({detail}). This agy build is not "
                f"recognised - left unmodified so it can report its own error."
            ), sha_orig
        if state == STATE_PATCHED:
            suffix = ""
            if missing_best_effort:
                suffix = f" (best-effort patterns absent: {', '.join(missing_best_effort)})"
            return True, f"Binary is already patched: {detail}{suffix}", sha_orig
        return True, "No matching signatures found.", sha_orig

    msg_body = ", ".join(applied_details)
    if exact_match:
        msg_body = f"[registered build {exact_match}] " + msg_body
    if skipped:
        msg_body += f" (skipped platform-specific: {', '.join(skipped)})"
    if missing_best_effort:
        msg_body += f" (best-effort absent: {', '.join(missing_best_effort)})"

    if dry_run:
        return True, f"[DRY-RUN] Would apply: {msg_body}", sha_orig

    backup_binary(agy_path, dry_run=False)

    err = _write_atomic(agy_path, data)
    if err is not None:
        return False, f"Failed writing patch: {err}", sha_orig

    return True, f"Patched: {msg_body}", compute_sha256(agy_path)
