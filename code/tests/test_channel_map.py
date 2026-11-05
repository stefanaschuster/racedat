#!/usr/bin/env python3
"""tests/test_channel_map.py — v22.6

Verifies:
  1. parse_channel_map() handles tabs, multi-space, header, BOM, blanks,
     commas with whitespace, unknown labels.
  2. CHANNEL_MAP loaded from parsers/channel_map.txt has the expected
     8 Standardkanäle.
  3. ROLES pattern_hints reflect the file content (case-insensitive
     exact-match regex per Datenkanal name).
  4. STANDARDKANAL_TO_ROLE_ID is complete (every role id has a label).
  5. assign_channels.find_matches() respects file order and matches
     case-insensitively.
  6. assign_channels.build_lookup_table() returns file-order tuples.
"""
import os
import sys
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from parsers.channel_roles import (
    parse_channel_map,
    CHANNEL_MAP,
    STANDARDKANAL_TO_ROLE_ID,
    ROLES,
    suggest_channel,
)
import assign_channels


class TestParseChannelMap(unittest.TestCase):
    def test_basic_tab_separated(self):
        text = "Standardkanal\tDatenkanal\n\nSchräglage\tphi_lean, Lean_Angle\n"
        result = parse_channel_map(text)
        self.assertEqual(result, {"Schräglage": ["phi_lean", "Lean_Angle"]})

    def test_header_row_skipped(self):
        text = "Standardkanal\tDatenkanal\nSchräglage\tphi_lean\n"
        result = parse_channel_map(text)
        self.assertNotIn("Standardkanal", result)

    def test_bom_stripped(self):
        text = "\ufeffSchräglage\tphi_lean\n"
        result = parse_channel_map(text)
        self.assertIn("Schräglage", result)

    def test_multi_space_separator(self):
        # No tab, but 2+ spaces after label
        text = "Schräglage   phi_lean, Lean_Angle\n"
        result = parse_channel_map(text)
        self.assertEqual(result.get("Schräglage"), ["phi_lean", "Lean_Angle"])

    def test_trailing_comma_ignored(self):
        text = "Schräglage\tphi_lean, Lean_Angle,\n"
        result = parse_channel_map(text)
        self.assertEqual(result["Schräglage"], ["phi_lean", "Lean_Angle"])

    def test_extra_whitespace_in_names(self):
        text = "Schräglage\t  phi_lean ,    Lean_Angle   \n"
        result = parse_channel_map(text)
        self.assertEqual(result["Schräglage"], ["phi_lean", "Lean_Angle"])

    def test_blank_lines_skipped(self):
        text = "\n\nSchräglage\tphi_lean\n\n\nBremsdruck\tBrake_Front\n"
        result = parse_channel_map(text)
        self.assertEqual(len(result), 2)

    def test_empty_input(self):
        self.assertEqual(parse_channel_map(""), {})
        self.assertEqual(parse_channel_map(None), {})

    def test_unknown_label_kept(self):
        # The parser doesn't validate against STANDARDKANAL_TO_ROLE_ID;
        # the caller (_apply_channel_map_to_roles) does the filtering.
        text = "Foobar\tsomething\n"
        result = parse_channel_map(text)
        self.assertIn("Foobar", result)

    def test_single_column_line_skipped(self):
        text = "Schräglage\nBremsdruck\tBrake_Front\n"
        result = parse_channel_map(text)
        self.assertNotIn("Schräglage", result)
        self.assertIn("Bremsdruck", result)


class TestChannelMapLoaded(unittest.TestCase):
    """Verifies the actual parsers/channel_map.txt loaded at import."""

    def test_eight_standardkanäle(self):
        # v22.7 — Erweitert von 8 auf 10 (Federweg Gabel + Federbein hinzu).
        # Name der Methode aus Backward-Compat-Gründen unverändert.
        self.assertEqual(len(CHANNEL_MAP), 10,
            f"Expected 10 Standardkanäle, got {len(CHANNEL_MAP)}: "
            f"{list(CHANNEL_MAP.keys())}")

    def test_all_labels_mapped_to_roles(self):
        # Every label in CHANNEL_MAP must have a role_id in STANDARDKANAL_TO_ROLE_ID
        for label in CHANNEL_MAP:
            self.assertIn(label, STANDARDKANAL_TO_ROLE_ID,
                f"CHANNEL_MAP has label {label!r} with no role mapping")

    def test_role_id_mapping_complete(self):
        # Every role in ROLES must have a Standardkanal label
        role_ids_in_map = set(STANDARDKANAL_TO_ROLE_ID.values())
        registry_role_ids = {r["id"] for r in ROLES}
        missing = registry_role_ids - role_ids_in_map
        self.assertEqual(missing, set(),
            f"Roles without Standardkanal label: {missing}")


class TestPatternHintsAfterApply(unittest.TestCase):
    """Verifies that ROLES.pattern_hints reflect the file content."""

    def test_lean_patterns_from_file(self):
        lean = next(r for r in ROLES if r["id"] == "lean")
        # All patterns should be ^name$ form
        for p in lean["pattern_hints"]:
            self.assertTrue(p.startswith("^") and p.endswith("$"),
                f"Pattern {p!r} is not anchored — expected ^name$")
        # The Datenkanäle from the file should appear, case-preserved
        # in the pattern but matched case-insensitively
        names_from_patterns = [p[1:-1] for p in lean["pattern_hints"]]
        # File: phi_lean, Lean_Angle, Bike_Angle, LeanAngle, Bank_abs
        # The patterns are re.escape()'d versions — _ stays _, but
        # we strip the anchors and check that the escaped name
        # de-escaped equals the file name.
        expected_names = ["phi_lean", "Lean_Angle", "Bike_Angle",
                          "LeanAngle", "Bank_abs"]
        for exp in expected_names:
            self.assertTrue(
                any(re.escape(exp) == p[1:-1] for p in lean["pattern_hints"]),
                f"Expected {exp!r} in lean pattern_hints, got "
                f"{lean['pattern_hints']}")

    def test_patterns_match_case_insensitive(self):
        # suggest_channel should match LEAN_ANGLE → lean role even though
        # the file has Lean_Angle (different case)
        lean = next(r for r in ROLES if r["id"] == "lean")
        # Available channels: one with mixed case that the file has
        available = [
            {"id": "ch_a", "name": "LEAN_ANGLE", "unit": "deg"},  # all-caps
            {"id": "ch_b", "name": "random_other", "unit": "deg"},
        ]
        result = suggest_channel(lean, available)
        self.assertEqual(result, "ch_a")

    def test_pattern_does_not_match_substring(self):
        # Now that we use ^name$, "Lean_Angle_Filtered" must NOT match
        # the Lean_Angle pattern.
        lean = next(r for r in ROLES if r["id"] == "lean")
        available = [
            {"id": "ch_a", "name": "Lean_Angle_Filtered", "unit": "deg"},
            {"id": "ch_b", "name": "irrelevant", "unit": "deg"},
        ]
        result = suggest_channel(lean, available)
        self.assertIsNone(result,
            "Substring match should NOT trigger with anchored patterns")


class TestAssignChannelsHelpers(unittest.TestCase):
    """Unit tests for the assign_channels script helpers."""

    def test_build_lookup_table_preserves_file_order(self):
        cm = {
            "Schräglage": ["phi_lean", "LeanAngle"],
            "Bremsdruck": ["Brake_Front"],
        }
        lookup = assign_channels.build_lookup_table(cm)
        # phi_lean must come before LeanAngle within Schräglage entries
        leans = [item for item in lookup if item[1] == "lean"]
        self.assertEqual([n[0] for n in leans], ["phi_lean", "leanangle"],
            "Lookup table must preserve file order within a role")

    def test_build_lookup_skips_unknown_labels(self):
        cm = {
            "Schräglage": ["phi_lean"],
            "UnknownLabel": ["foo"],
        }
        lookup = assign_channels.build_lookup_table(cm)
        rids = {r for _, r, _ in lookup}
        self.assertEqual(rids, {"lean"})

    def test_find_matches_basic(self):
        lookup = [("phi_lean", "lean", "phi_lean"),
                  ("brake_front", "brake_pressure", "Brake_Front")]
        extras = {
            "ch_1": {"name": "phi_lean", "unit": "deg", "data": [1, 2]},
            "ch_2": {"name": "Brake_Front", "unit": "bar", "data": [3, 4]},
            "ch_3": {"name": "irrelevant", "unit": "", "data": []},
        }
        result = assign_channels.find_matches(extras, lookup)
        self.assertEqual(result, {"lean": "ch_1", "brake_pressure": "ch_2"})

    def test_find_matches_case_insensitive(self):
        lookup = [("phi_lean", "lean", "phi_lean")]
        extras = {
            "ch_1": {"name": "PHI_LEAN", "unit": "deg", "data": [1]},
        }
        result = assign_channels.find_matches(extras, lookup)
        self.assertEqual(result, {"lean": "ch_1"})

    def test_find_matches_first_in_file_order_wins(self):
        # If a lap has both phi_lean AND LeanAngle, phi_lean (listed
        # first in the file) should win.
        lookup = [
            ("phi_lean", "lean", "phi_lean"),
            ("leanangle", "lean", "LeanAngle"),
        ]
        extras = {
            "ch_first":  {"name": "LeanAngle", "unit": "deg", "data": [1]},
            "ch_second": {"name": "phi_lean",  "unit": "deg", "data": [2]},
        }
        result = assign_channels.find_matches(extras, lookup)
        # phi_lean wins because it's first in the lookup
        self.assertEqual(result["lean"], "ch_second")

    def test_find_matches_no_match(self):
        lookup = [("phi_lean", "lean", "phi_lean")]
        extras = {
            "ch_1": {"name": "something_else", "unit": "deg", "data": [1]},
        }
        result = assign_channels.find_matches(extras, lookup)
        self.assertEqual(result, {})

    def test_find_matches_empty_extras(self):
        lookup = [("phi_lean", "lean", "phi_lean")]
        self.assertEqual(assign_channels.find_matches({}, lookup), {})
        self.assertEqual(assign_channels.find_matches(None, lookup), {})


if __name__ == "__main__":
    unittest.main()
