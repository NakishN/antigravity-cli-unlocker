"""
Default-model control for agy.

Why this module exists
----------------------
The binary patch clears the *client-side* eligibility gate.  Google's
*server-side* source-IP gate is separate, and it is attached to the Gemini
family rather than to every model.  Measured 2026-10-27 from a real Russian
egress (``95.26.84.28``, AS8402 Vimpelcom, Kazan), patched ``agy 1.4.8``, no
VPN and no proxy, changing only ``--model``:

===========================  ==================================================
``gemini-3.8-flash-low``     ``FAILED_PRECONDITION (400): User location is not
                             supported for the API use``
``claude-sonnet-4-6``        ``RU_CLAUDE_OK``
``gpt-oss-120b-medium``      ``RU_GPTOSS_OK``
===========================  ==================================================

So the cheapest working install in a blocked region needs no foreign exit at
all: switch agy's default away from Gemini.  That matters because the TUI
starts on Gemini, so a user who never types ``/model`` gets the 400 on every
request even though the patch is doing its job.

Where the default lives
-----------------------
``~/.gemini/antigravity-cli/settings.json``, top-level ``"model"`` key.  It
stores the *display* name (``"Claude Sonnet 4.6 (Thinking)"``), while
``agy --model`` accepts the *id* (``claude-sonnet-4-6``); the two are not
interchangeable in the file.  This was verified by editing exactly that value
and running ``agy -p`` with no ``--model``: before the edit it answered the
region 400, after the edit it answered ``DEFAULT_CLAUDE_OK``.

Only that one key is rewritten.  The rest of the file - including the large
permission list agy owns - is left byte-for-byte alone where possible, the
original is backed up once, and ``restore`` puts it back.
"""

import json
import os
import re
import shutil
import subprocess

SETTINGS_RELPATH = os.path.join(".gemini", "antigravity-cli", "settings.json")
BACKUP_SUFFIX = ".antigravity-unlock.bak"

# Non-Gemini models, best first.  Claude is preferred because it answered from
# a Russian IP while Gemini was refused; gpt-oss is the last resort.
RU_MODEL_IDS = (
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
)

# Used when `agy models` cannot be asked (offline, not signed in, old build).
# These are the display names agy 1.4.8 prints; the ids above are what the CLI
# accepts.
FALLBACK_DISPLAY_NAMES = {
    "claude-sonnet-4-6": "Claude Sonnet 4.6 (Thinking)",
    "claude-opus-4-6-thinking": "Claude Opus 4.6 (Thinking)",
    "gpt-oss-120b-medium": "GPT-OSS 120B (Medium)",
}

DEFAULT_RU_MODEL_ID = RU_MODEL_IDS[0]
MODELS_TIMEOUT = 60.0


class ModelSettingsError(Exception):
    """The settings file is missing, unreadable, or not shaped as expected."""


def get_settings_path(home=None):
    """Absolute path of agy's settings file."""
    base = home or os.path.expanduser("~")
    return os.path.join(base, SETTINGS_RELPATH)


def get_backup_path(path=None):
    """Where the pre-change settings file is kept."""
    return (path or get_settings_path()) + BACKUP_SUFFIX


def _read_raw(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise ModelSettingsError(
            f"agy settings not found at {path} - start agy once (for example "
            f"'agy models') so it creates the file, then retry"
        )
    except OSError as e:
        raise ModelSettingsError(f"cannot read {path}: {e}")


def read_settings(path=None):
    """Parse agy's settings file.  Raises :class:`ModelSettingsError`."""
    path = path or get_settings_path()
    raw = _read_raw(path)
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ModelSettingsError(f"{path} is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ModelSettingsError(f"{path} does not contain a JSON object")
    return data


def default_model(path=None):
    """The model agy starts with, or ``None`` when the key is absent."""
    return read_settings(path).get("model")


def backup_model(path=None):
    """The model saved in the backup file, or ``None`` when there is no backup."""
    backup = get_backup_path(path)
    try:
        with open(backup, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data.get("model") if isinstance(data, dict) else None


def is_gemini_model(name):
    """True for any Gemini display name.

    The server-side gate was measured on the Gemini family; treating any name
    containing ``gemini`` as gated is deliberately conservative.  A name we do
    not recognise is *not* assumed safe - callers should only report "not
    Gemini" as a positive statement when the identity is clear.
    """
    return bool(name) and "gemini" in str(name).lower()


def _parse_models_output(text):
    """Parse ``agy models`` into ``[{"id": ..., "name": ...}]``.

    Observed format on 1.4.8 is one model per line, id and display name
    separated by a tab.  Two-or-more spaces are accepted as well, and a line
    without a separator is kept as an id with an empty name.
    """
    models = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("fetching"):
            continue
        if "\t" in line:
            mid, name = line.split("\t", 1)
        else:
            parts = re.split(r"\s{2,}", line, maxsplit=1)
            mid, name = (parts[0], parts[1]) if len(parts) == 2 else (line, "")
        mid = mid.strip()
        if not mid or mid.startswith("-"):
            continue
        models.append({"id": mid, "name": name.strip()})
    return models


def available_models(agy_path, timeout=MODELS_TIMEOUT):
    """Ask agy for its model list.  Returns ``[]`` when that is not possible."""
    if not agy_path:
        return []
    try:
        proc = subprocess.run(
            [agy_path, "models"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return _parse_models_output((proc.stdout or "") + (proc.stderr or ""))


def resolve_model_choice(choice, agy_path=None, timeout=MODELS_TIMEOUT):
    """Turn a CLI id or a display name into ``(id, display_name)``.

    Raises :class:`ModelSettingsError` when the value matches nothing agy
    reports.  The settings file needs the display name, so an unknown id must
    not be written there: agy would silently fall back to its built-in default,
    which is exactly the Gemini model this command exists to avoid.
    """
    if not choice or not str(choice).strip():
        raise ModelSettingsError("no model given")

    wanted = str(choice).strip()
    models = available_models(agy_path, timeout=timeout)

    for m in models:
        if m["id"] == wanted:
            return m["id"], m["name"] or FALLBACK_DISPLAY_NAMES.get(m["id"], m["id"])
    lowered = wanted.lower()
    for m in models:
        if m["name"] and m["name"].lower() == lowered:
            return m["id"], m["name"]

    if models:
        known = ", ".join(m["id"] for m in models)
        raise ModelSettingsError(
            f"unknown model {wanted!r}.  agy reports: {known}"
        )

    # agy could not be asked.  Accept the ids we know, and any display name that
    # looks like one (contains a space) rather than guessing an unknown id.
    if wanted in FALLBACK_DISPLAY_NAMES:
        return wanted, FALLBACK_DISPLAY_NAMES[wanted]
    if " " in wanted:
        return wanted, wanted
    raise ModelSettingsError(
        f"cannot resolve {wanted!r}: 'agy models' did not answer, and the value "
        f"is not a known model id or a display name"
    )


def choose_ru_model(agy_path=None, preferred=None, timeout=MODELS_TIMEOUT):
    """Pick a non-Gemini model that agy reports, best first.

    Returns ``(id, display_name)``.  ``preferred`` is resolved first when given.
    """
    if preferred and str(preferred).strip().lower() not in ("", "ru"):
        mid, name = resolve_model_choice(preferred, agy_path=agy_path, timeout=timeout)
        if is_gemini_model(name) or is_gemini_model(mid):
            raise ModelSettingsError(
                f"{preferred!r} is a Gemini model, and Gemini is the family Google "
                f"refuses from a blocked region; choose claude-* or gpt-oss-*"
            )
        return mid, name

    models = available_models(agy_path, timeout=timeout)
    by_id = {m["id"]: m for m in models}
    for mid in RU_MODEL_IDS:
        if mid in by_id:
            m = by_id[mid]
            return mid, m["name"] or FALLBACK_DISPLAY_NAMES[mid]

    # No list: fall back to the measured names.  agy will reject a stale name at
    # the next start, which is visible, rather than silently using Gemini.
    for mid in RU_MODEL_IDS:
        if mid in FALLBACK_DISPLAY_NAMES:
            return mid, FALLBACK_DISPLAY_NAMES[mid]
    raise ModelSettingsError("no non-Gemini model to select")


_MODEL_KEY_RE = re.compile(r'("model"\s*:\s*)"((?:[^"\\]|\\.)*)"')


def _replace_model_key(raw, new_name):
    """Rewrite the top-level ``model`` value, preserving the rest verbatim.

    Returns the new text.  Falls back to a full re-serialisation when a textual
    edit cannot be proven equivalent, so a nested ``model`` key or unusual
    whitespace can never silently change the wrong field.
    """
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ModelSettingsError("settings file is not a JSON object")

    matches = list(_MODEL_KEY_RE.finditer(raw))
    if len(matches) == 1:
        m = matches[0]
        replacement = m.group(1) + json.dumps(new_name, ensure_ascii=False)
        candidate = raw[:m.start()] + replacement + raw[m.end():]
        try:
            check = json.loads(candidate)
        except ValueError:
            check = None
        if isinstance(check, dict) and check.get("model") == new_name:
            expected = dict(data)
            expected["model"] = new_name
            if check == expected:
                return candidate

    data["model"] = new_name
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if raw.endswith("\n"):
        text += "\n"
    return text


def set_default_model(model_name, path=None, backup=True):
    """Set agy's default model.  Returns ``(ok, message)``.

    The backup is created once, before the first change, and never overwritten:
    repeated calls must not replace the user's original Gemini default with the
    value this module itself wrote.
    """
    path = path or get_settings_path()
    raw = _read_raw(path)
    try:
        current = json.loads(raw).get("model")
    except ValueError as e:
        raise ModelSettingsError(f"{path} is not valid JSON: {e}")

    if current == model_name:
        return True, f"agy already starts with {model_name!r} (nothing to change)"

    if backup:
        bak = get_backup_path(path)
        if not os.path.exists(bak):
            try:
                shutil.copy2(path, bak)
            except OSError as e:
                return False, f"cannot create backup {bak}: {e}"

    new_raw = _replace_model_key(raw, model_name)

    tmp = path + ".antigravity-unlock.tmp"
    try:
        mode = os.stat(path).st_mode
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_raw)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False, f"cannot write {path}: {e}"

    message = f"agy now starts with {model_name!r} (was {current!r})"
    if backup and os.path.exists(get_backup_path(path)):
        message += f"; original saved to {get_backup_path(path)}"
    message += ".  Changes apply to the next agy launch."
    return True, message


def restore_default_model(path=None):
    """Put the backed-up settings file back.  Returns ``(ok, message)``."""
    path = path or get_settings_path()
    bak = get_backup_path(path)
    if not os.path.exists(bak):
        return False, f"no backup at {bak}; nothing to restore"
    try:
        before = default_model(path)
    except ModelSettingsError:
        before = None
    try:
        shutil.copy2(bak, path)
    except OSError as e:
        return False, f"cannot restore {path} from {bak}: {e}"
    try:
        after = default_model(path)
    except ModelSettingsError:
        after = None
    return True, f"restored {path} from backup (model {before!r} -> {after!r})"
