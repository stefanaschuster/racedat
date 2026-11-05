"""v22.10 — Tests for the thresholds loader.

Verifies:
  1. The shipped thresholds.json is loadable, well-formed, and matches
     the FALLBACK structure (no drift between file and module).
  2. Merge behaviour: partial files, missing sections, type mismatches,
     extra keys.
  3. Comment-key stripping (keys starting with '_').
  4. Robustness: missing file, malformed JSON, non-dict top-level.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import thresholds


class TestShippedFile(unittest.TestCase):
    """The bundled thresholds.json loads, has all FALLBACK sections,
    and the loaded values match the FALLBACK defaults."""

    def test_loaded_top_level_sections(self):
        loaded = thresholds.THRESHOLDS
        for section in thresholds.FALLBACK:
            self.assertIn(section, loaded,
                f"loaded thresholds is missing section {section!r}")

    def test_fallback_keys_present_after_strip(self):
        # After stripping comment-keys, every leaf key from FALLBACK
        # must be present in the stripped tree.
        stripped = thresholds.get_thresholds()
        for section, defaults in thresholds.FALLBACK.items():
            self.assertIn(section, stripped)
            for key in defaults:
                self.assertIn(key, stripped[section],
                    f"key {section!r}.{key!r} missing after strip")

    def test_file_values_match_fallback_for_known_keys(self):
        # The .json defaults should match FALLBACK byte-for-byte, otherwise
        # the "file missing" semantics drift from "file present" semantics.
        stripped = thresholds.get_thresholds()
        for section, defaults in thresholds.FALLBACK.items():
            for key, fb_val in defaults.items():
                loaded_val = stripped[section][key]
                # int vs float ist okay (json macht aus 5 oft 5.0)
                if isinstance(fb_val, (int, float)) and isinstance(loaded_val, (int, float)):
                    self.assertAlmostEqual(loaded_val, fb_val, places=10,
                        msg=f"value mismatch at {section}.{key}: "
                            f"file={loaded_val} fallback={fb_val}")
                else:
                    self.assertEqual(loaded_val, fb_val,
                        f"value mismatch at {section}.{key}")


class TestStripComments(unittest.TestCase):
    def test_strips_underscore_keys(self):
        d = {"a": 1, "_comment": "x", "nested": {"b": 2, "_about": "y"}}
        out = thresholds.strip_comments(d)
        self.assertEqual(out, {"a": 1, "nested": {"b": 2}})

    def test_preserves_lists(self):
        d = {"_x": "skip", "arr": [1, 2, {"_inner": "skip", "k": 3}]}
        out = thresholds.strip_comments(d)
        self.assertEqual(out, {"arr": [1, 2, {"k": 3}]})

    def test_handles_scalars(self):
        self.assertEqual(thresholds.strip_comments(42), 42)
        self.assertEqual(thresholds.strip_comments("hi"), "hi")
        self.assertEqual(thresholds.strip_comments(None), None)


class TestMergeWithFallback(unittest.TestCase):
    def setUp(self):
        self.fb = {
            "brake": {"a": 0.05, "b": 8},
            "accel": {"c": 1.0, "d": 95},
        }

    def test_empty_loaded_returns_fallback(self):
        out = thresholds.merge_with_fallback({}, self.fb)
        self.assertEqual(out, self.fb)

    def test_partial_section_filled_from_fallback(self):
        # User only sets one key in 'brake' — the other inherits from fb
        out = thresholds.merge_with_fallback({"brake": {"a": 0.99}}, self.fb)
        self.assertEqual(out["brake"]["a"], 0.99)
        self.assertEqual(out["brake"]["b"], 8)  # fallback

    def test_missing_section_inherits(self):
        out = thresholds.merge_with_fallback({"brake": {"a": 0.99}}, self.fb)
        self.assertEqual(out["accel"], self.fb["accel"])

    def test_extra_key_kept(self):
        # Stefan can add new keys without editing fallback (forward-compat)
        out = thresholds.merge_with_fallback(
            {"brake": {"a": 0.05, "b": 8, "new_key": "hello"}}, self.fb)
        self.assertEqual(out["brake"]["new_key"], "hello")

    def test_extra_section_kept(self):
        out = thresholds.merge_with_fallback(
            {"new_section": {"x": 1}}, self.fb)
        self.assertIn("new_section", out)
        self.assertEqual(out["new_section"]["x"], 1)

    def test_type_mismatch_falls_back(self):
        # User puts a string where fallback has a number → fallback wins
        out = thresholds.merge_with_fallback({"brake": {"a": "broken"}}, self.fb)
        self.assertEqual(out["brake"]["a"], 0.05)  # fallback

    def test_int_float_interchangeable(self):
        out = thresholds.merge_with_fallback({"brake": {"a": 1}}, self.fb)
        self.assertEqual(out["brake"]["a"], 1)  # int accepted where float expected

    def test_non_dict_section_falls_back(self):
        out = thresholds.merge_with_fallback({"brake": "not-a-dict"}, self.fb)
        self.assertEqual(out["brake"], self.fb["brake"])


class TestLoad(unittest.TestCase):
    def test_missing_file_returns_fallback(self):
        out = thresholds.load("/nonexistent/path/thresholds.json")
        # Sections in fallback should be present
        for section in thresholds.FALLBACK:
            self.assertIn(section, out)

    def test_malformed_json_returns_fallback(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                          delete=False) as fh:
            fh.write("this is not valid JSON {{{")
            path = fh.name
        try:
            out = thresholds.load(path)
            for section in thresholds.FALLBACK:
                self.assertIn(section, out)
        finally:
            os.unlink(path)

    def test_non_dict_toplevel_returns_fallback(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                          delete=False) as fh:
            fh.write('[1, 2, 3]')  # array, not object
            path = fh.name
        try:
            out = thresholds.load(path)
            for section in thresholds.FALLBACK:
                self.assertIn(section, out)
        finally:
            os.unlink(path)

    def test_partial_file_merges_with_fallback(self):
        custom = {"suspension_bump": {"k_mad": 9.99}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                          delete=False) as fh:
            json.dump(custom, fh)
            path = fh.name
        try:
            out = thresholds.load(path)
            self.assertEqual(out["suspension_bump"]["k_mad"], 9.99)
            # Other keys in the section came from fallback
            self.assertEqual(out["suspension_bump"]["safety_floor_mm_s"],
                             thresholds.FALLBACK["suspension_bump"]["safety_floor_mm_s"])
            # Other sections are pure fallback
            self.assertEqual(out["brake"], thresholds.FALLBACK["brake"])
        finally:
            os.unlink(path)


class TestGetThresholds(unittest.TestCase):
    def test_strips_comments(self):
        out = thresholds.get_thresholds()
        # Every section must have no underscore-keys after strip
        for section, body in out.items():
            for key in body:
                self.assertFalse(key.startswith("_"),
                    f"comment-key {section}.{key} not stripped")


class TestCoachIntegration(unittest.TestCase):
    """v22.10 — Schutz gegen "orphaned" Config-Keys im JS.

    Wenn ein JS-Detektor `cfg.foo_bar ?? 0.5` liest, aber `foo_bar`
    nicht im FALLBACK existiert, würde der Wert immer den Default `0.5`
    nehmen — die JSON-Konfiguration hätte keinen Effekt, ohne dass es
    auffällt. Dieser Test fängt das ab indem er das gerenderte Coach-HTML
    nach allen `cfg.NAME ??`-Vorkommen durchsucht und prüft, dass jeder
    NAME in mindestens einer FALLBACK-Sektion existiert.
    """

    def test_no_orphan_cfg_keys(self):
        import coach
        import re
        html = coach.build_coach_empty_html(maptiler_key="")
        # Matched Patterns wie `cfg.foo_bar ??`, `brCfg.foo_bar ??`,
        # `aCfg.foo_bar ??` — die drei Konvention-Aliase im Coach-JS
        pattern = re.compile(r"(?:cfg|brCfg|aCfg)\.([a-z_][a-z0-9_]*)\s*\?\?")
        found = set(pattern.findall(html))
        all_fallback_keys = set()
        for section_cfg in thresholds.FALLBACK.values():
            all_fallback_keys.update(section_cfg.keys())
        orphans = found - all_fallback_keys
        self.assertEqual(orphans, set(),
            f"JS-Detektoren lesen Config-Keys, die nicht im FALLBACK "
            f"existieren: {sorted(orphans)}. Entweder im JS umbenennen "
            f"oder in thresholds.py + thresholds.json ergänzen.")

    def test_html_contains_thresholds_blob(self):
        import coach
        html = coach.build_coach_empty_html(maptiler_key="")
        # Placeholder muss ersetzt sein
        self.assertNotIn("{{THRESHOLDS_JSON}}", html,
            "Placeholder wurde nicht ersetzt")
        # Eine echte THRESHOLDS-Konstante muss da sein
        self.assertIn("const THRESHOLDS = ", html)
        self.assertIn("window.THRESHOLDS = THRESHOLDS;", html)


if __name__ == "__main__":
    unittest.main()
