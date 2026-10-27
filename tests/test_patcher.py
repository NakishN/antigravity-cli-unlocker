"""
Tests for Binary Patcher and SHA-256 validation.
"""

import os
import unittest
import tempfile

from antigravity_unlock.patcher import (
    OUTCOME_ALREADY_PATCHED,
    OUTCOME_PATCHED,
    OUTCOME_SIGNATURE_MISSING,
    STATE_FOREIGN,
    STATE_PATCHED,
    STATE_UNPATCHED,
    backup_binary,
    classify_binary,
    compute_sha256,
    count_needles_stream,
    get_backup_info,
    get_backup_path,
    inspect_binary,
    list_pattern_names,
    patch_binary,
    repatch_if_needed,
    restore_binary,
    unpatch_binary,
    _apply_patterns,
)


class _TempBinaryMixin:
    """Writes a throwaway 'binary' and cleans up it and its backup."""

    def _make(self, content):
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(content)
        f.close()
        path = f.name
        self.addCleanup(os.unlink, path)
        backup = get_backup_path(path)
        self.addCleanup(lambda: os.path.exists(backup) and os.unlink(backup))
        return path

    def _read(self, path):
        with open(path, "rb") as f:
            return f.read()


class TestPatcher(_TempBinaryMixin, unittest.TestCase):
    def test_compute_sha256(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            tmp_path = f.name
        try:
            sha = compute_sha256(tmp_path)
            self.assertEqual(sha, "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
        finally:
            os.unlink(tmp_path)

    def test_patch_and_restore_wildcard(self):
        content = b"header_data_0123_ineligible_footer_name=ineligible_data"
        tmp_path = self._make(content)

        orig_size = len(content)
        success, msg, sha = patch_binary(tmp_path)
        self.assertTrue(success)

        patched_content = self._read(tmp_path)
        self.assertEqual(len(patched_content), orig_size)
        self.assertIn(b"inexigible", patched_content)
        self.assertNotIn(b"ineligible", patched_content)

        rec_ok, rec_msg = restore_binary(tmp_path)
        self.assertTrue(rec_ok)
        self.assertEqual(self._read(tmp_path), content)

    def test_no_pattern_rewrites_user_visible_error_text(self):
        # Regression: `Eligibility check failed: %w` is a *generic* error wrapper
        # in agy, not an eligibility-specific string - it also wraps unrelated
        # failures such as a profile-picture TLS timeout.  Renaming it to
        # "...bypass" made real errors unreadable, and renaming "Agent execution
        # terminated due to error." actively hid the cause.  Only wire-level
        # field names may be touched.
        from antigravity_unlock.patcher import load_versions_db

        for wp in load_versions_db().get("wildcard_patterns", []):
            original = bytes.fromhex(wp["pattern"])
            for banned in (b"check failed", b"terminated", b"bypass"):
                self.assertNotIn(
                    banned, original,
                    f"{wp['name']} rewrites user-visible error text",
                )


class TestStreamCounting(unittest.TestCase):
    """The streamed census must agree with a whole-file count.

    ``count_needles_stream`` carries a suffix across chunk boundaries and
    subtracts it again, so small chunk sizes are what exercise the join logic.
    A divergence here would let the guardian believe a binary is patched when it
    is not.
    """

    def _assert_counts_match(self, data, needles, chunk_size):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = f.name
        try:
            streamed = count_needles_stream(path, needles, chunk_size=chunk_size)
            for n in needles:
                self.assertEqual(
                    streamed[n], data.count(n),
                    f"streamed count for {n!r} diverged at chunk_size={chunk_size}",
                )
        finally:
            os.unlink(path)

    def test_matches_whole_file_count_across_chunk_sizes(self):
        needles = [b"ineligible", b"inexigible", b"name=ineligible"]
        # Matches placed to straddle boundaries at several chunk sizes, plus a
        # truncated match at EOF (the case that loses a deferred tail count).
        data = (b"x" * 100 + b"ineligible" + b"y" * 7 + b"ineligible"
                + b"name=ineligible" + b"z" * 200 + b"inexigible" + b"inelig")
        for chunk_size in (1, 3, 9, 10, 11, 14, 15, 64, 4096):
            with self.subTest(chunk_size=chunk_size):
                self._assert_counts_match(data, needles, chunk_size)

    def test_match_at_eof_is_counted(self):
        # The needle ends exactly at EOF, so it sits in the carried tail when the
        # read loop exits.
        data = b"padding" * 50 + b"ineligible"
        for chunk_size in (1, 7, 13):
            with self.subTest(chunk_size=chunk_size):
                self._assert_counts_match(data, [b"ineligible"], chunk_size)

    def test_file_smaller_than_carry_window(self):
        # Regression: re-adding the final tail at EOF double-counted every match
        # inside it.  That only shows up when the file is shorter than
        # max(len(needle)) - 1, so keep one long needle in the set to widen the
        # window past the file length.
        data = b"ineligible name=ineligible"
        needles = [b"ineligible", b"name=ineligible",
                   b"Agent execution terminated due to error."]
        for chunk_size in (1, 8, 26, 4096):
            with self.subTest(chunk_size=chunk_size):
                self._assert_counts_match(data, needles, chunk_size)

    def test_empty_and_absent_needles(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"nothing relevant here")
            path = f.name
        try:
            self.assertEqual(count_needles_stream(path, []), {})
            self.assertEqual(count_needles_stream(path, [b""]), {})
            self.assertEqual(count_needles_stream(path, [b"ineligible"])[b"ineligible"], 0)
        finally:
            os.unlink(path)


class TestClassifyBinary(_TempBinaryMixin, unittest.TestCase):
    """classify_binary drives every 'is it patched?' decision in the tool."""

    def test_unpatched_when_primary_present(self):
        path = self._make(b"pad name=ineligible pad ineligible pad")
        state, detail = classify_binary(path)
        self.assertEqual(state, STATE_UNPATCHED)
        self.assertIn("ineligible", detail)

    def test_patched_after_rename(self):
        path = self._make(b"pad name=ineligible pad ineligible pad")
        patch_binary(path)
        state, detail = classify_binary(path)
        self.assertEqual(state, STATE_PATCHED)
        data = self._read(path)
        self.assertNotIn(b"ineligible", data)
        self.assertIn(b"inexigible", data)

    def test_foreign_when_neither_form_present(self):
        # Neither the signature nor its replacement: an unrecognised build.
        # Reporting this as 'patched' is the dangerous failure mode - it would
        # let the tool claim success on a binary it never touched.
        path = self._make(b"#!/bin/sh\necho a totally different binary layout\n")
        state, _ = classify_binary(path)
        self.assertEqual(state, STATE_FOREIGN)

    def test_patching_preserves_size_exactly(self):
        # Every rename is same-length by construction; a size change would shift
        # offsets and relocations in a ~220 MB executable.
        path = self._make(b"aaa ineligible bbb name=ineligible ccc Account ineligible ddd")
        before = os.path.getsize(path)
        patch_binary(path)
        self.assertEqual(os.path.getsize(path), before)

    def test_bare_rename_subsumes_the_struct_tag_form(self):
        # The bare literal must also catch the serialized protobuf descriptor
        # occurrences, not just the Go struct tags - that consistency is the
        # whole point of preferring it over the narrower `name=ineligible`.
        path = self._make(b"descriptor\x0a\nineligible json\x12\nineligible tag name=ineligible")
        info = inspect_binary(path, include_optional=False)
        primary = info["primary"]
        self.assertEqual(primary["name"], "protobuf_ineligible_bare")
        self.assertEqual(primary["original_hits"], 3)

        patch_binary(path)
        data = self._read(path)
        self.assertEqual(data.count(b"inexigible"), 3)
        self.assertNotIn(b"ineligible", data)

    def test_go_type_identifiers_are_untouched(self):
        # The rename is case-sensitive on purpose: Go type and field names such
        # as IneligibleTier / IneligibleInfo must survive, or the binary stops
        # linking its own symbols.
        path = self._make(b"IneligibleTier IneligibleInfo ineligible IneligibleTiers")
        patch_binary(path)
        data = self._read(path)
        self.assertIn(b"IneligibleTier", data)
        self.assertIn(b"IneligibleInfo", data)
        self.assertNotIn(b" ineligible", data)


class TestOptionalPatterns(_TempBinaryMixin, unittest.TestCase):
    def test_optional_patterns_excluded_by_default(self):
        # The https_proxy rename stops agy honouring the user's own proxy env,
        # and the machine-code gates are byte-exact per build.  Neither may be
        # applied unless explicitly requested.
        path = self._make(b"ineligible and https_proxy and HTTPS_PROXY")

        patch_binary(path)
        data = self._read(path)
        self.assertIn(b"https_proxy", data, "optional proxy rename leaked into a default patch")
        self.assertNotIn(b"AG_LS_PROXY", data)

        restore_binary(path)
        patch_binary(path, include_optional=True)
        data = self._read(path)
        self.assertIn(b"AG_LS_PROXY", data)
        self.assertIn(b"HTTPS_PROXY", data, "the upper-case var must be left alone")


class TestRepatchIfNeeded(_TempBinaryMixin, unittest.TestCase):
    """The guardian depends on these outcomes staying distinct."""

    def test_repatches_a_reverted_binary(self):
        path = self._make(b"pad ineligible pad")
        patch_binary(path)
        # Simulate an agy self-update restoring the stock bytes.
        with open(path, "wb") as f:
            f.write(b"pad ineligible pad")

        outcome, msg = repatch_if_needed(path)
        self.assertEqual(outcome, OUTCOME_PATCHED)
        self.assertIn(b"inexigible", self._read(path))

    def test_already_patched_is_not_reported_as_repatched(self):
        path = self._make(b"pad ineligible pad")
        patch_binary(path)
        outcome, msg = repatch_if_needed(path)
        self.assertEqual(outcome, OUTCOME_ALREADY_PATCHED)

    def test_unrecognised_build_is_left_alone(self):
        # 'signature missing' must never be conflated with 'already patched':
        # the first means update the tool, the second means nothing to do.
        path = self._make(b"a totally different binary layout")
        before = self._read(path)
        outcome, msg = repatch_if_needed(path)
        self.assertEqual(outcome, OUTCOME_SIGNATURE_MISSING)
        self.assertEqual(self._read(path), before)

    def test_dry_run_does_not_write(self):
        path = self._make(b"pad ineligible pad")
        outcome, msg = repatch_if_needed(path, dry_run=True)
        self.assertIn("DRY-RUN", msg)
        self.assertIn(b"ineligible", self._read(path))

    def test_missing_file_is_a_failure_not_a_foreign_build(self):
        outcome, msg = repatch_if_needed("/nonexistent/path/to/agy")
        self.assertEqual(outcome, "failed")


class TestUnpatchRoundTrip(_TempBinaryMixin, unittest.TestCase):
    """unpatch must be exact: it is the restore path that works after a
    self-update, when the stored backup belongs to an older build."""

    def test_unpatch_reverses_patch_byte_for_byte(self):
        content = (b"pad ineligible pad name=ineligible pad Account ineligible "
                   b"IneligibleTier IneligibleInfo tail")
        path = self._make(content)

        patch_binary(path)
        self.assertNotEqual(self._read(path), content)

        ok, msg, _ = unpatch_binary(path)
        self.assertTrue(ok)
        self.assertIn("Reverted", msg)
        self.assertEqual(self._read(path), content,
                         "unpatch did not restore the original bytes exactly")

    def test_unpatch_on_pristine_binary_is_a_noop(self):
        content = b"pad ineligible pad"
        path = self._make(content)
        ok, msg, _ = unpatch_binary(path)
        self.assertTrue(ok)
        self.assertIn("Nothing to revert", msg)
        self.assertEqual(self._read(path), content)

    def test_unpatch_preserves_size(self):
        path = self._make(b"aaa ineligible bbb name=ineligible ccc")
        before = os.path.getsize(path)
        patch_binary(path)
        unpatch_binary(path)
        self.assertEqual(os.path.getsize(path), before)

    def test_unpatch_dry_run_does_not_write(self):
        path = self._make(b"pad ineligible pad")
        patch_binary(path)
        patched = self._read(path)
        _, msg, _ = unpatch_binary(path, dry_run=True)
        self.assertIn("DRY-RUN", msg)
        self.assertEqual(self._read(path), patched)

    def test_unpatch_leaves_optional_patterns_alone_by_default(self):
        path = self._make(b"ineligible https_proxy HTTPS_PROXY")
        patch_binary(path, include_optional=True)
        unpatch_binary(path)  # default: optional not included
        data = self._read(path)
        self.assertIn(b"ineligible", data)
        self.assertIn(b"AG_LS_PROXY", data, "optional rename must survive a default unpatch")

        unpatch_binary(path, include_optional=True)
        self.assertIn(b"https_proxy", self._read(path))


class TestBackupFreshness(_TempBinaryMixin, unittest.TestCase):
    """A stale backup makes `restore` a silent downgrade."""

    def test_stale_backup_is_refreshed_from_a_pristine_binary(self):
        path = self._make(b"old build ineligible")
        backup, created = backup_binary(path)
        self.assertTrue(created)

        # agy self-updates: different size, still pristine.
        with open(path, "wb") as f:
            f.write(b"a newer and longer build ineligible")
        info = get_backup_info(path)
        self.assertTrue(info["stale"], "size mismatch must be reported as stale")

        _, refreshed = backup_binary(path)
        self.assertTrue(refreshed)
        self.assertFalse(get_backup_info(path)["stale"])
        self.assertEqual(self._read(backup), self._read(path))

    def test_patched_binary_never_overwrites_the_backup(self):
        # The backup is the only way back; clobbering it with a patched image
        # would make `restore` a no-op.
        path = self._make(b"pristine ineligible")
        backup, _ = backup_binary(path)
        pristine = self._read(backup)

        patch_binary(path)
        backup_binary(path)
        self.assertEqual(self._read(backup), pristine,
                         "backup was overwritten with a patched image")

    def test_missing_backup_for_patched_binary_is_reported_not_faked(self):
        path = self._make(b"already inexigible")
        patch_binary(path)  # no-op rename target absent, but classify sees patched
        backup, created = backup_binary(path)
        self.assertFalse(created)
        self.assertFalse(os.path.exists(backup))


class TestOnlyAllowlist(unittest.TestCase):
    """``only`` exists because ``include_optional`` is all-or-nothing.

    The optional tier mixes two very different kinds of change: length-preserving
    string renames, safe on any build, and byte-exact machine-code rewrites whose
    offsets were taken from one specific build.  agy self-updates without asking,
    so applying the latter blind is how a 220 MB binary gets corrupted.  The
    egress shell hook needs exactly one of them - ``proxy_var_isolation`` - and
    measured on agy 1.2.11 ``--include-optional`` would also have rewritten
    ``ineligibility_from_result_gate``, a 16-byte machine-code pattern.
    """

    def test_registry_exposes_the_names_the_flag_validates_against(self):
        names = list_pattern_names()
        self.assertIn("proxy_var_isolation", names)
        self.assertIn("protobuf_ineligible_bare", names)
        self.assertEqual(len(names), len(set(names)), "duplicate pattern names")

    def test_only_applies_an_optional_pattern_without_the_flag(self):
        data = bytearray(b"a https_proxy b ineligible c")
        applied, _, _ = _apply_patterns(data, only=["proxy_var_isolation"])
        self.assertEqual(applied, ["proxy_var_isolation (1x)"])
        self.assertIn(b"AG_LS_PROXY", bytes(data))

    def test_only_leaves_unrequested_patterns_alone(self):
        # The primary rename is safe, but an allowlist that leaks is not an
        # allowlist.
        data = bytearray(b"a https_proxy b ineligible c")
        _apply_patterns(data, only=["proxy_var_isolation"])
        self.assertIn(b"ineligible", bytes(data))
        self.assertNotIn(b"inexigible", bytes(data))

    def test_only_can_select_a_primary_pattern(self):
        data = bytearray(b"ineligible")
        applied, _, _ = _apply_patterns(data, only=["protobuf_ineligible_bare"])
        self.assertEqual(applied, ["protobuf_ineligible_bare (1x)"])
        self.assertEqual(bytes(data), b"inexigible")

    def test_only_does_not_apply_everything_by_default(self):
        without = bytearray(b"https_proxy ineligible")
        _apply_patterns(without)
        self.assertIn(b"https_proxy", bytes(without), "optional tier must stay off")
        self.assertIn(b"inexigible", bytes(without))

    def test_empty_allowlist_means_no_restriction(self):
        # argparse yields None when the flag is absent, and a caller passing []
        # means the same.  Treating [] as "apply nothing" would silently no-op.
        data = bytearray(b"ineligible")
        applied, _, _ = _apply_patterns(data, only=[])
        self.assertTrue(any("protobuf_ineligible_bare" in a for a in applied), applied)

    def test_unknown_name_applies_nothing(self):
        data = bytearray(b"https_proxy ineligible")
        applied, _, _ = _apply_patterns(data, only=["typo_not_a_pattern"])
        self.assertEqual(applied, [])
        self.assertEqual(bytes(data), b"https_proxy ineligible")


if __name__ == "__main__":
    unittest.main()
