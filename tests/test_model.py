"""
Tests for the default-model switch.

The behaviour that matters is narrow and was measured, not guessed: agy reads
its default from the top-level ``model`` key of
``~/.gemini/antigravity-cli/settings.json``, that value is a display name
rather than the CLI id, and changing only it made ``agy -p`` answer from a
Russian IP where Gemini had just been refused.  These tests pin the file
handling: one key changed, the rest preserved, the original backed up once,
and a restore that puts the user's file back.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from antigravity_unlock import model


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


class TestSettingsPath(unittest.TestCase):
    def test_uses_home(self):
        path = model.get_settings_path("/home/alice")
        self.assertEqual(
            path,
            os.path.join("/home/alice", ".gemini", "antigravity-cli", "settings.json"),
        )

    def test_backup_is_next_to_settings(self):
        self.assertEqual(
            model.get_backup_path("/tmp/s.json"),
            "/tmp/s.json" + model.BACKUP_SUFFIX,
        )


class TestDefaultModel(unittest.TestCase):
    def test_reads_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            _write(path, {"model": "Gemini 3.8 Flash (High)", "autoUpdate": True})
            self.assertEqual(model.default_model(path), "Gemini 3.8 Flash (High)")

    def test_missing_file_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(model.ModelSettingsError) as ctx:
                model.default_model(os.path.join(d, "nope.json"))
            self.assertIn("start agy once", str(ctx.exception))

    def test_invalid_json_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")
            with self.assertRaises(model.ModelSettingsError):
                model.default_model(path)

    def test_non_object_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[]")
            with self.assertRaises(model.ModelSettingsError):
                model.default_model(path)


class TestModelIdentity(unittest.TestCase):
    def test_gemini_names(self):
        self.assertTrue(model.is_gemini_model("Gemini 3.8 Flash (High)"))
        self.assertTrue(model.is_gemini_model("gemini-3.8-flash-low"))
        self.assertFalse(model.is_gemini_model("Claude Sonnet 4.6 (Thinking)"))
        self.assertFalse(model.is_gemini_model(None))
        self.assertFalse(model.is_gemini_model(""))

    def test_parse_models_output(self):
        text = (
            "Fetching available models...\n"
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n"
            "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
        )
        parsed = model._parse_models_output(text)
        self.assertEqual([m["id"] for m in parsed],
                         ["gemini-3.8-flash-high", "claude-sonnet-4-6",
                          "gpt-oss-120b-medium"])
        self.assertEqual(parsed[1]["name"], "Claude Sonnet 4.6 (Thinking)")

    def test_parse_models_output_two_space_separator(self):
        parsed = model._parse_models_output("x\tX Name\ny  Y Name\n")
        self.assertEqual(parsed[1], {"id": "y", "name": "Y Name"})


class TestResolveChoice(unittest.TestCase):
    MODELS = [
        {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)"},
        {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"},
    ]

    def test_id_resolves_to_display_name(self):
        with patch.object(model, "available_models", return_value=self.MODELS):
            mid, name = model.resolve_model_choice("claude-sonnet-4-6", "agy")
        self.assertEqual(mid, "claude-sonnet-4-6")
        self.assertEqual(name, "Claude Sonnet 4.6 (Thinking)")

    def test_display_name_is_accepted(self):
        with patch.object(model, "available_models", return_value=self.MODELS):
            mid, name = model.resolve_model_choice(
                "Claude Sonnet 4.6 (Thinking)", "agy"
            )
        self.assertEqual(mid, "claude-sonnet-4-6")
        self.assertEqual(name, "Claude Sonnet 4.6 (Thinking)")

    def test_unknown_value_lists_what_is_available(self):
        with patch.object(model, "available_models", return_value=self.MODELS):
            with self.assertRaises(model.ModelSettingsError) as ctx:
                model.resolve_model_choice("no-such-model", "agy")
        self.assertIn("unknown model", str(ctx.exception))
        self.assertIn("claude-sonnet-4-6", str(ctx.exception))

    def test_offline_accepts_known_id_and_display_name(self):
        with patch.object(model, "available_models", return_value=[]):
            mid, name = model.resolve_model_choice("claude-sonnet-4-6", "agy")
            self.assertEqual(name, "Claude Sonnet 4.6 (Thinking)")
            mid, name = model.resolve_model_choice("Some Model (Preview)", "agy")
            self.assertEqual(name, "Some Model (Preview)")

    def test_offline_rejects_an_unknown_id(self):
        with patch.object(model, "available_models", return_value=[]):
            with self.assertRaises(model.ModelSettingsError):
                model.resolve_model_choice("totally-unknown", "agy")


class TestChooseRuModel(unittest.TestCase):
    MODELS = [
        {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)"},
        {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)"},
        {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"},
    ]

    def test_prefers_claude_sonnet(self):
        with patch.object(model, "available_models", return_value=self.MODELS):
            mid, name = model.choose_ru_model("agy")
        self.assertEqual(mid, "claude-sonnet-4-6")
        self.assertEqual(name, "Claude Sonnet 4.6 (Thinking)")

    def test_preferred_non_gemini_is_honoured(self):
        with patch.object(model, "available_models", return_value=self.MODELS):
            mid, name = model.choose_ru_model("agy", preferred="gpt-oss-120b-medium")
        self.assertEqual(mid, "gpt-oss-120b-medium")

    def test_preferred_gemini_is_refused(self):
        with patch.object(model, "available_models", return_value=self.MODELS):
            with self.assertRaises(model.ModelSettingsError) as ctx:
                model.choose_ru_model("agy", preferred="gemini-3.8-flash-high")
        self.assertIn("Gemini", str(ctx.exception))

    def test_falls_back_when_agy_cannot_be_asked(self):
        with patch.object(model, "available_models", return_value=[]):
            mid, name = model.choose_ru_model("agy")
        self.assertEqual(mid, "claude-sonnet-4-6")
        self.assertEqual(name, model.FALLBACK_DISPLAY_NAMES[mid])


class TestSetAndRestore(unittest.TestCase):
    def _settings(self, d, data=None):
        path = os.path.join(d, "settings.json")
        payload = data or {
            "model": "Gemini 3.8 Flash (High)",
            "autoUpdate": True,
            "permissions": {"allow": ["command(git)"]},
        }
        _write(path, payload)
        return path

    def test_sets_only_the_model_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._settings(d)
            ok, msg = model.set_default_model("Claude Sonnet 4.6 (Thinking)", path=path)
            self.assertTrue(ok, msg)
            after = json.load(open(path, encoding="utf-8"))
            self.assertEqual(after["model"], "Claude Sonnet 4.6 (Thinking)")
            self.assertTrue(after["autoUpdate"])
            self.assertEqual(after["permissions"], {"allow": ["command(git)"]})

    def test_backup_holds_the_original(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._settings(d)
            ok, _ = model.set_default_model("Claude Sonnet 4.6 (Thinking)", path=path)
            self.assertTrue(ok)
            backup = model.get_backup_path(path)
            self.assertTrue(os.path.exists(backup))
            self.assertEqual(model.backup_model(path), "Gemini 3.8 Flash (High)")

    def test_second_change_does_not_overwrite_the_original_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._settings(d)
            model.set_default_model("Claude Sonnet 4.6 (Thinking)", path=path)
            model.set_default_model("GPT-OSS 120B (Medium)", path=path)
            self.assertEqual(model.backup_model(path), "Gemini 3.8 Flash (High)")
            self.assertEqual(
                json.load(open(path, encoding="utf-8"))["model"],
                "GPT-OSS 120B (Medium)",
            )

    def test_same_value_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._settings(d)
            ok, msg = model.set_default_model("Gemini 3.8 Flash (High)", path=path)
            self.assertTrue(ok)
            self.assertIn("already", msg)
            self.assertFalse(os.path.exists(model.get_backup_path(path)))

    def test_restore_puts_the_original_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._settings(d)
            model.set_default_model("Claude Sonnet 4.6 (Thinking)", path=path)
            ok, msg = model.restore_default_model(path)
            self.assertTrue(ok, msg)
            self.assertEqual(
                json.load(open(path, encoding="utf-8"))["model"],
                "Gemini 3.8 Flash (High)",
            )

    def test_restore_without_backup_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._settings(d)
            ok, msg = model.restore_default_model(path)
            self.assertFalse(ok)
            self.assertIn("no backup", msg)

    def test_preserves_unknown_fields_verbatim(self):
        """A textual edit must not reformat the permissions block agy owns."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            original = (
                '{\n'
                '  "autoUpdate": true,\n'
                '  "model": "Gemini 3.8 Flash (High)",\n'
                '  "permissions": {\n'
                '    "allow": [\n'
                '      "command(git)",\n'
                '      "command(cat)"\n'
                '    ]\n'
                '  }\n'
                '}\n'
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(original)
            ok, msg = model.set_default_model("Claude Sonnet 4.6 (Thinking)", path=path)
            self.assertTrue(ok, msg)
            after = open(path, encoding="utf-8").read()
            self.assertIn('"command(cat)"', after)
            # Everything except the one value is byte-identical.
            restored = after.replace(
                "Claude Sonnet 4.6 (Thinking)", "Gemini 3.8 Flash (High)"
            )
            self.assertEqual(restored, original)

    def test_missing_file_is_reported_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "absent.json")
            with self.assertRaises(model.ModelSettingsError):
                model.set_default_model("Claude Sonnet 4.6 (Thinking)", path=path)
            self.assertFalse(os.path.exists(path))

    def test_a_nested_model_key_is_not_rewritten(self):
        """Only the top-level key matters; the fallback must pick the right one."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            _write(path, {
                "model": "Gemini 3.8 Flash (High)",
                "someSection": {"model": "nested-value"},
            })
            ok, msg = model.set_default_model("Claude Sonnet 4.6 (Thinking)", path=path)
            self.assertTrue(ok, msg)
            after = json.load(open(path, encoding="utf-8"))
            self.assertEqual(after["model"], "Claude Sonnet 4.6 (Thinking)")
            self.assertEqual(after["someSection"]["model"], "nested-value")


if __name__ == "__main__":
    unittest.main()
