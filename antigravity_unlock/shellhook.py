"""
Shell integration for the egress route.

``runner.py`` sets the proxy environment for the process it execs, which covers
``antigravity-unlock run``.  It cannot cover the case that actually matters most:
the user types ``agy``.  A wrapper nobody invokes is not a fix, and asking people
to change a habit they have already formed is how tools get uninstalled.

So this writes a small marked block into the shell's startup file.  Two
properties are non-negotiable, and both come from things this project got wrong
before:

- **It sets ``AG_LS_PROXY``, never ``https_proxy``.**  Exporting ``https_proxy``
  from a shell profile redirects *everything* - git, curl, package managers,
  every other CLI - through a tunnel built for one program.  ``AG_LS_PROXY`` is
  read by agy alone, and only once the opt-in ``proxy_var_isolation`` pattern has
  renamed the lower-case ``https_proxy`` literal in the binary to it.  That patch
  is therefore a prerequisite, and ``install`` refuses without it rather than
  quietly falling back to the global variable.
- **The block is delimited and removal is exact.**  ``hosts_cleanup`` exists
  because 1.4.x wrote unmarked lines into ``/etc/hosts`` that a later ``unpin()``
  could no longer recognise.  Every line here sits between markers, and
  ``remove`` deletes only what is between them.

One caveat worth knowing: the rename replaces the *lower-case* literal only, so
agy still honours an ambient ``HTTPS_PROXY`` if the user has one set, and Go
consults that spelling first.  ``status`` reports it when present.
"""

import os

from antigravity_unlock.discovery import get_primary_agy
from antigravity_unlock.egress import proxy_var_is_isolated

HOOK_BEGIN = "# >>> antigravity-unlocker egress >>>"
HOOK_END = "# <<< antigravity-unlocker egress <<<"

# agy reads AG_LS_PROXY only after the proxy_var_isolation rename is applied.
REQUIRED_PATTERN = "proxy_var_isolation"


def _shell_name():
    shell = os.environ.get("SHELL") or ""
    return os.path.basename(shell).lower()


def profile_path(shell=None):
    """The startup file for *shell*, or None when we do not handle it.

    fish is deliberately excluded: its syntax is not POSIX ``export``, and
    writing a broken line into someone's config.fish is worse than telling them
    what to add.
    """
    name = (shell or _shell_name()).lower()
    home = os.path.expanduser("~")
    if name in ("bash", "sh", "dash"):
        for candidate in (".bashrc", ".profile"):
            path = os.path.join(home, candidate)
            if os.path.exists(path):
                return path
        return os.path.join(home, ".bashrc")
    if name == "zsh":
        return os.path.join(home, ".zshrc")
    return None


def _block(url):
    return "\n".join([
        HOOK_BEGIN,
        "# Managed by: antigravity-unlock egress hook install|remove",
        "# Sends agy (and only agy) through the configured exit.  Nothing else",
        "# reads this variable.  Requires the proxy_var_isolation patch.",
        'export AG_LS_PROXY="%s"' % url,
        HOOK_END,
    ])


def find_block(text):
    """Return ``(start, end)`` offsets of the managed block, or None."""
    start = text.find(HOOK_BEGIN)
    if start < 0:
        return None
    end = text.find(HOOK_END, start)
    if end < 0:
        return None
    return start, end + len(HOOK_END)


def current_url(path=None):
    """The AG_LS_PROXY value in the managed block, or None."""
    path = path or profile_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    span = find_block(text)
    if span is None:
        return None
    for line in text[span[0]:span[1]].splitlines():
        line = line.strip()
        if line.startswith("export AG_LS_PROXY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def install(url, path=None, agy_path=None):
    """Write or refresh the managed block.  Returns ``(ok, message)``."""
    if not url:
        return False, "no route URL to install"

    # Verified before writing, never after.  A block agy silently ignores is
    # worse than an error: it looks installed, reads correctly, and does nothing.
    if not agy_path:
        agy_path = get_primary_agy()
    if not agy_path:
        return False, (
            "no agy binary was found, so there is no way to check that it would "
            "read AG_LS_PROXY.  Install Antigravity CLI, then re-run."
        )
    if not proxy_var_is_isolated(agy_path):
        return False, (
            "agy does not read AG_LS_PROXY yet: the opt-in %s pattern is not "
            "applied.  Run 'antigravity-unlock patch --include-optional' first.  "
            "Without it the only variable agy honours is https_proxy, and "
            "exporting that from a shell profile would route git, curl and every "
            "other tool through the tunnel too." % REQUIRED_PATTERN
        )

    path = path or profile_path()
    if path is None:
        return False, (
            "unsupported shell %r - add this line to your shell's startup file "
            "manually:\n  export AG_LS_PROXY=\"%s\"" % (_shell_name(), url)
        )

    text = ""
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError as e:
            return False, "cannot read %s: %s" % (path, e)

    block = _block(url)
    span = find_block(text)
    if span is not None:
        if text[span[0]:span[1]] == block:
            return True, "%s already up to date" % path
        text = text[:span[0]] + block + text[span[1]:]
        action = "updated"
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block + "\n"
        action = "added"

    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as e:
        return False, "cannot write %s: %s" % (path, e)

    return True, (
        "%s block in %s\n"
        "  export AG_LS_PROXY=\"%s\"\n"
        "Open a new shell (or 'source %s') for it to take effect."
        % (action, path, url, path)
    )


def remove(path=None):
    """Delete the managed block and nothing else.  Returns ``(ok, message)``."""
    path = path or profile_path()
    if path is None:
        return False, "unsupported shell %r - remove the AG_LS_PROXY line by hand" % _shell_name()
    if not os.path.isfile(path):
        return False, "%s does not exist" % path

    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as e:
        return False, "cannot read %s: %s" % (path, e)

    span = find_block(text)
    if span is None:
        return True, "no managed block in %s - nothing to remove" % path

    cleaned = (text[:span[0]] + text[span[1]:]).strip("\n")
    cleaned = cleaned + "\n" if cleaned else ""
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(cleaned)
    except OSError as e:
        return False, "cannot write %s: %s" % (path, e)

    return True, "removed the managed block from %s" % path


def ambient_proxy_conflict():
    """The ambient upper-case proxy variable agy would prefer, or None.

    The rename covers the lower-case literal only, so an exported HTTPS_PROXY
    still wins over AG_LS_PROXY.  Worth reporting rather than silently
    overriding: it is the user's variable, not ours.
    """
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(name)
        if value:
            return name, value
    return None
