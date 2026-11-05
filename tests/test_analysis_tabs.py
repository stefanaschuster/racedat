"""v21.41 — Verify the Coach SPA's analysis chooser renders as a tab strip
with the expected tabs, ids, and ARIA wiring. Pure markup-level test:
parses the rendered HTML and checks the relevant pieces are present.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import coach

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def main():
    html = coach.build_coach_empty_html(maptiler_key="")

    print("\n== Tab strip markup ==")
    check("an-tabs-wrap container present",
          'id="an-tabs-wrap"' in html)
    check("an-tabs role=tablist container present",
          'class="an-tabs" role="tablist"' in html)

    expected_tabs = [
        ("brake",       "BREMSEN",          False),
        ("accel",       "BESCHLEUNIGEN",    False),
        ("electronics", "ELEKTRONIK-SETUP", False),
        ("suspension",  "FAHRWERKS-SETUP",  False),
        ("mistakes",    "FAHRFEHLER",       True),
        ("technique",   "TECHNIK",          True),
    ]
    for key, label, is_soon in expected_tabs:
        tab_attr = f'data-an="{key}"'
        check(f"tab '{key}' present", tab_attr in html)
        if is_soon:
            # The soon tabs have class="an-tab soon" and aria-disabled
            soon_pat = re.compile(
                r'class="an-tab soon"[^>]*data-an="' + re.escape(key) + r'"')
            check(f"tab '{key}' marked as soon",
                  bool(soon_pat.search(html)) or 'soon' in _slice_tab(html, key))
            check(f"tab '{key}' has aria-disabled",
                  'aria-disabled="true"' in _slice_tab(html, key))
        else:
            # Available tabs have role=tab and aria-selected (initial "false";
            # the JS flips one to "true" on load).
            tab_block = _slice_tab(html, key)
            check(f"tab '{key}' has role=tab",
                  'role="tab"' in tab_block)
            check(f"tab '{key}' has aria-selected",
                  'aria-selected=' in tab_block)
        check(f"tab '{key}' shows label {label}",
              label in _slice_tab(html, key))

    print("\n== Panels container ==")
    check("an-content present",
          'class="an-content" id="an-content"' in html)
    for key, _label, _ in expected_tabs:
        check(f"panel-{key} present", f'id="panel-{key}"' in html)
        check(f"panel-{key} has role=tabpanel",
              f'id="panel-{key}"' in html and
              'role="tabpanel"' in _slice_panel(html, key))

    print("\n== Old card chooser removed ==")
    # The old structure (an-choice-grid, an-panel-wrap, an-panel-body)
    # must not appear in rendered HTML. (Comment lines in source mention
    # them for the changelog — those don't make it into rendered HTML
    # because they're inside the <script>'s real comments? They're inside
    # the python triple-string so they DO render. So we only check the
    # *attribute / class* uses, not the words themselves.)
    check("no class='an-choice-grid'",
          "class=\"an-choice-grid\"" not in html and
          "class='an-choice-grid'" not in html)
    check("no class='an-choice'",
          'class="an-choice"' not in html and
          'class="an-choice ' not in html)
    check("no id='an-panel-wrap'",
          'id="an-panel-wrap"' not in html)
    check("no class='an-panel-wrap'",
          'class="an-panel-wrap"' not in html)
    check("no class='an-panel-body'",
          'class="an-panel-body"' not in html)
    check("no class='an-panel-head'",
          'class="an-panel-head"' not in html)

    print("\n== Switch logic present ==")
    check("setupAnalysisChoice IIFE present",
          'setupAnalysisChoice' in html)
    check("activates 'first available' default",
          'firstAvail' in html)
    check("does not bind 'soon' tabs",
          "classList.contains('soon')" in html and "BALD-Tabs nicht binden" in html)

    print("\n== Section title text ==")
    check("section title is 'ANALYSE' (not 'WÄHLEN')",
          '<h2>ANALYSE</h2>' in html)

    print("\n== v22.8 — Suspension panel layout order ==")
    # Stefan: das Histogramm soll ÜBER der Trackmap stehen. Damit ein
    # zukünftiger Edit das nicht versehentlich zurückkippt, fixieren wir
    # die DOM-Reihenfolge:
    #   slot-picker → hist-section → trackmap → analyse-container → chart
    panel_start = html.find('id="panel-suspension"')
    check("panel-suspension exists", panel_start > -1)
    if panel_start > -1:
        # Suchen nach Markern relativ zum Panel-Start
        slot_pos  = html.find('id="suspension-slots"',  panel_start)
        hist_pos  = html.find('id="susp-hist-section"', panel_start)
        tmap_pos  = html.find('id="susp-trackmap-wrap"', panel_start)
        analy_pos = html.find('id="suspension-analysis"', panel_start)
        chart_pos = html.find('id="susp-chart-section"', panel_start)
        check("slot-picker present in panel",  slot_pos  > -1)
        check("hist-section present in panel", hist_pos  > -1)
        check("trackmap present in panel",     tmap_pos  > -1)
        check("analysis-container in panel",   analy_pos > -1)
        check("chart-section present in panel", chart_pos > -1)
        check("order: slot-picker < hist-section",
              slot_pos < hist_pos,
              f"slot={slot_pos}, hist={hist_pos}")
        check("order: hist-section < trackmap (v22.8: hist über map)",
              hist_pos < tmap_pos,
              f"hist={hist_pos}, trackmap={tmap_pos}")
        check("order: trackmap < analysis-container",
              tmap_pos < analy_pos,
              f"trackmap={tmap_pos}, analysis={analy_pos}")
        check("order: analysis-container < chart-section",
              analy_pos < chart_pos,
              f"analysis={analy_pos}, chart={chart_pos}")

    print(f"\n{PASS} pass, {FAIL} fail")
    return 0 if FAIL == 0 else 1


def _slice_tab(html, key):
    """Return the substring around a tab's <button …> opener, including
    its inner content. Cheap regex slice — enough for assertions about
    attributes present near the tab opener."""
    pat = re.compile(
        r'<button[^>]*data-an="' + re.escape(key) + r'"[^>]*>.*?</button>',
        re.DOTALL,
    )
    m = pat.search(html)
    return m.group(0) if m else ""


def _slice_panel(html, key):
    pat = re.compile(
        r'<div[^>]*id="panel-' + re.escape(key) + r'"[^>]*>',
        re.DOTALL,
    )
    m = pat.search(html)
    return m.group(0) if m else ""


if __name__ == "__main__":
    sys.exit(main())
