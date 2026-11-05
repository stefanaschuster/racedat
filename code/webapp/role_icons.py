"""v22.4/v22.5 — Role-icon SVGs, single source of truth.

One small inline SVG per channel role, used by:
  - sessions.html (server-rendered, _channel_dots helper in webserver.py)
  - coach.py picker (JS, fetched via /api/channel-roles-registry)
  - report_single.py Datenviewer picker (JS, same endpoint)
  - report.py Compare picker (JS, same endpoint)

v22.5: webapp/analyze.html and webapp/upload.html were removed —
they were old prototype files no longer served. The real Datenviewer
picker template lives in report_single.py's _PAGE_TEMPLATE; the
Compare picker template lives in report.py's _TEMPLATE. The
test_picker_icons_wired.py regression test fails fast if either
template loses its icon wiring.

Design rules so colour-switching (grey ↔ green) works uniformly:
  - viewBox 14×14, no width/height attribute on the SVG itself
    (the CSS sets a fixed size via .ch-icon { width:14px; height:14px })
  - All strokes/fills use `currentColor` so the parent .ch-icon's
    `color:` cascades in. The .on/.off classes only set color.
  - Default stroke-width 1.5; fill="none" unless the shape needs fill.
  - Lines should be flat and read as silhouettes at 14px — no thin
    detail under 1 pixel.

The icons themselves are intentionally simple/iconic, not photorealistic.
They need to be recognisable at 14×14 in a row of 8, not look pretty
at 200×200.
"""
from typing import Dict


# Each value is a complete <svg ...>...</svg> tag, ready to inline.
ROLE_ICONS: Dict[str, str] = {
    # Brake disc — outer circle with 6 ventilation holes; small inner hub.
    "brake_pressure": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.2" stroke-linecap="round">'
        '<circle cx="7" cy="7" r="5.5"/>'
        '<circle cx="7" cy="7" r="1.3" fill="currentColor" stroke="none"/>'
        # 6 small ventilation holes between hub and rim
        '<circle cx="7" cy="3.3" r="0.55" fill="currentColor" stroke="none"/>'
        '<circle cx="10.2" cy="5.2" r="0.55" fill="currentColor" stroke="none"/>'
        '<circle cx="10.2" cy="8.8" r="0.55" fill="currentColor" stroke="none"/>'
        '<circle cx="7" cy="10.7" r="0.55" fill="currentColor" stroke="none"/>'
        '<circle cx="3.8" cy="8.8" r="0.55" fill="currentColor" stroke="none"/>'
        '<circle cx="3.8" cy="5.2" r="0.55" fill="currentColor" stroke="none"/>'
        '</svg>'
    ),

    # Lean angle — tilted bike silhouette: simplified as two angled wheel-dots
    # connected by a leaning vertical line; suggests motorcycle banking right.
    # We draw an upright reference line + a tilted line crossing it at the
    # bottom to read as "tilt angle".
    "lean": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">'
        # Ground line
        '<line x1="1.5" y1="12" x2="12.5" y2="12"/>'
        # Tilted bike body (line from ground at center to top-right)
        '<line x1="7" y1="12" x2="11.5" y2="3"/>'
        # Wheel at ground
        '<circle cx="7" cy="12" r="1.1" fill="currentColor" stroke="none"/>'
        # Tiny arc showing the angle between vertical and tilt
        '<path d="M 7 8 A 4 4 0 0 1 9 9.2"/>'
        '</svg>'
    ),

    # Throttle (Gasgriff) — handlebar grip: a horizontal cylinder with
    # grip ridges suggesting the rotating part.
    "throttle": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">'
        # Handlebar (thin horizontal)
        '<line x1="1.5" y1="7" x2="3.5" y2="7"/>'
        # Grip body (rounded rect)
        '<rect x="3.5" y="4.5" width="8.5" height="5" rx="1.2"/>'
        # Grip ridges
        '<line x1="5.5" y1="5.3" x2="5.5" y2="8.7"/>'
        '<line x1="7"   y1="5.3" x2="7"   y2="8.7"/>'
        '<line x1="8.5" y1="5.3" x2="8.5" y2="8.7"/>'
        '<line x1="10"  y1="5.3" x2="10"  y2="8.7"/>'
        '</svg>'
    ),

    # Throttle butterfly (Drosselklappe) — circular bore with a tilted
    # ellipse (the butterfly plate) and the shaft line across the middle.
    "throttle_butterfly": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.2" stroke-linecap="round">'
        # Throttle body (circle)
        '<circle cx="7" cy="7" r="5.5"/>'
        # Butterfly plate (tilted ellipse, semi-open ~30°)
        '<ellipse cx="7" cy="7" rx="5" ry="2" '
        'transform="rotate(-30 7 7)" '
        'fill="currentColor" fill-opacity="0.35"/>'
        # Shaft (horizontal line through center)
        '<line x1="1.5" y1="7" x2="12.5" y2="7"/>'
        '</svg>'
    ),

    # Front wheel speed — wheel with "F" mark inside (front).
    # Use a tyre (outer + inner circle) + a small letter that reads at 14px.
    "wheel_speed_front": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.2">'
        # Tyre
        '<circle cx="7" cy="7" r="5.5"/>'
        '<circle cx="7" cy="7" r="3"/>'
        # "V" mark (Vorne) — small chevron pointing up
        '<path d="M 5.2 7.6 L 7 5.6 L 8.8 7.6" '
        'fill="none" stroke="currentColor" stroke-width="1.3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    ),

    # Rear wheel speed — same tyre but with chevron pointing DOWN (hinten/back).
    "wheel_speed_rear": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.2">'
        '<circle cx="7" cy="7" r="5.5"/>'
        '<circle cx="7" cy="7" r="3"/>'
        # "H" mark (Hinten) — chevron pointing down
        '<path d="M 5.2 6.4 L 7 8.4 L 8.8 6.4" '
        'fill="none" stroke="currentColor" stroke-width="1.3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    ),

    # TC status — text badge "TC" in a rounded rectangle. Keep it minimal:
    # a flat outlined pill with bold letters reads better at 14px than any
    # attempt at a "traction control" icon.
    "tc_status": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.1">'
        '<rect x="1" y="3.5" width="12" height="7" rx="1.5"/>'
        '<text x="7" y="9" text-anchor="middle" '
        'font-family="JetBrains Mono, monospace" '
        'font-size="5.5" font-weight="700" '
        'fill="currentColor" stroke="none">TC</text>'
        '</svg>'
    ),

    # WC status — same shape, "WC".
    "wc_status": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.1">'
        '<rect x="1" y="3.5" width="12" height="7" rx="1.5"/>'
        '<text x="7" y="9" text-anchor="middle" '
        'font-family="JetBrains Mono, monospace" '
        'font-size="5.5" font-weight="700" '
        'fill="currentColor" stroke="none">WC</text>'
        '</svg>'
    ),

    # v22.7 — Fork (Gabel): two parallel telescopic tubes connected by a
    # triple-clamp bar at the top. Reads as "front fork" silhouette at 14px.
    "suspension_fork": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.2" stroke-linecap="round">'
        # triple-clamp bar at the top
        '<line x1="3" y1="2.2" x2="11" y2="2.2"/>'
        # two fork tubes
        '<line x1="4.5" y1="2.2" x2="4.5" y2="11.5"/>'
        '<line x1="9.5" y1="2.2" x2="9.5" y2="11.5"/>'
        # axle line connecting both tubes at the bottom
        '<line x1="3.5" y1="11.8" x2="10.5" y2="11.8"/>'
        '</svg>'
    ),

    # v22.7 — Shock absorber (Federbein): cylinder body at the top with a
    # coil spring (zigzag) wound around the lower shaft. Iconic side view.
    "suspension_shock": (
        '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
        'class="ch-icon" fill="none" stroke="currentColor" '
        'stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">'
        # top eyelet
        '<circle cx="7" cy="2" r="1" fill="currentColor" stroke="none"/>'
        # damper body (cylinder, simplified as a tall rectangle)
        '<rect x="5.5" y="3" width="3" height="3.2" rx="0.4"/>'
        # coil spring: zigzag from below the body to bottom eyelet
        '<path d="M5 6.5 L9 7.5 L5 8.5 L9 9.5 L5 10.5 L9 11.5"/>'
        # bottom eyelet
        '<circle cx="7" cy="12.3" r="0.9" fill="currentColor" stroke="none"/>'
        '</svg>'
    ),
}


def icon_for(role_id: str) -> str:
    """Return the SVG for `role_id`, or a fallback dot if unknown.

    The fallback keeps us safe if a new role is added to channel_roles.py
    but the icon set isn't updated — the dot remains visible (and still
    colours correctly through currentColor), so the UI degrades gracefully
    instead of going blank.
    """
    return ROLE_ICONS.get(role_id, _FALLBACK_DOT)


_FALLBACK_DOT = (
    '<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" '
    'class="ch-icon" fill="currentColor"><circle cx="7" cy="7" r="3"/></svg>'
)
