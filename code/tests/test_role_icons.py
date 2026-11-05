#!/usr/bin/env python3
"""tests/test_role_icons.py — v22.4

Verifies that:
  1. Every channel role in parsers.channel_roles.ROLES has an icon in
     webapp.role_icons.ROLE_ICONS (no orphan roles → no blank squares
     in the picker).
  2. Each icon is a valid-shaped SVG snippet (starts with <svg, ends
     with </svg>, has a viewBox, uses currentColor so the wrapper's
     color: cascades in).
  3. icon_for() returns the icon for known roles and a non-empty
     fallback for unknown ones (graceful degradation).
  4. No icon hardcodes a fill="#..." or stroke="#..." colour that would
     break the grey/green switching.
"""
import os
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from webapp.role_icons import ROLE_ICONS, icon_for, _FALLBACK_DOT
from parsers.channel_roles import ROLES as CHANNEL_ROLES


class TestRoleIcons(unittest.TestCase):

    # -- completeness: every role has an icon ---------------------------------

    def test_every_role_has_an_icon(self):
        missing = [r["id"] for r in CHANNEL_ROLES if r["id"] not in ROLE_ICONS]
        self.assertEqual(missing, [],
            f"roles without an icon: {missing}")

    def test_no_orphan_icons(self):
        # Icons without a matching role would mean dead code — flag it.
        role_ids = {r["id"] for r in CHANNEL_ROLES}
        orphans = [k for k in ROLE_ICONS if k not in role_ids]
        self.assertEqual(orphans, [],
            f"icons without a matching role (dead code): {orphans}")

    # -- shape: each icon is a well-formed SVG snippet ------------------------

    def test_each_icon_is_svg(self):
        for rid, svg in ROLE_ICONS.items():
            with self.subTest(role=rid):
                self.assertTrue(svg.startswith("<svg "),
                    f"{rid}: doesn't start with <svg")
                self.assertTrue(svg.rstrip().endswith("</svg>"),
                    f"{rid}: doesn't end with </svg>")
                # viewBox is required so the wrapper can size at 14×14
                self.assertIn("viewBox=", svg,
                    f"{rid}: missing viewBox attr")
                # Class hook so the CSS .ch-icon { width:14px } applies
                self.assertIn('class="ch-icon"', svg,
                    f"{rid}: missing class=ch-icon")

    # -- color discipline: currentColor only ----------------------------------

    def test_no_hardcoded_colours(self):
        """SVGs must use currentColor (or no colour attr) only — otherwise
        the wrapper's color: won't be able to switch grey ↔ green."""
        hex_re = re.compile(r"#[0-9a-fA-F]{3,6}\b")
        named_re = re.compile(
            r'(?:fill|stroke)="(?!none|currentColor|transparent)'
            r'(?:red|green|blue|black|white|grey|gray|yellow|orange)"'
        )
        for rid, svg in ROLE_ICONS.items():
            with self.subTest(role=rid):
                self.assertFalse(hex_re.search(svg),
                    f"{rid}: hex colour found — must use currentColor")
                self.assertFalse(named_re.search(svg),
                    f"{rid}: named colour found — must use currentColor")

    # -- icon_for() behaviour -------------------------------------------------

    def test_icon_for_known_role(self):
        # Returns the same string as the dict for known ids
        self.assertEqual(icon_for("brake_pressure"),
                         ROLE_ICONS["brake_pressure"])

    def test_icon_for_unknown_role(self):
        # Returns the fallback (non-empty SVG, not "")
        out = icon_for("nonexistent_role_xyz")
        self.assertTrue(out.startswith("<svg "))
        self.assertIn("currentColor", out)
        self.assertEqual(out, _FALLBACK_DOT)

    def test_fallback_is_visible(self):
        # Sanity: the fallback isn't empty or broken
        self.assertTrue(_FALLBACK_DOT.startswith("<svg "))
        self.assertIn("</svg>", _FALLBACK_DOT)


if __name__ == "__main__":
    unittest.main()
