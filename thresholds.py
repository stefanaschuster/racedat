"""v22.10 — Detector thresholds loader.

Single source of truth for the AI Coach detector thresholds. The
thresholds.json file (in the repo root, alongside this module) is
Stefan-edited; this module:

  1. Loads it at import time, validates it loosely (must be a dict,
     known top-level sections allowed, unknown keys ignored).
  2. Merges with a hardcoded FALLBACK dict so a missing or partial
     file never crashes the server.
  3. Exposes THRESHOLDS (loaded+merged) and a helper get_thresholds()
     used by webserver.py to serve them to the coach SPA.

The JSON keys starting with '_' are documentation comments — they're
preserved during load but stripped by strip_comments() when handed
to consumers, so the over-the-wire payload to the browser stays slim.

Why module-level load + fallback dict (not lazy/cache):
  Same pattern as parsers/channel_roles.py:CHANNEL_MAP — file lives
  with the code, gets loaded once, fallback covers a missing-file
  scenario. Server-Restart picks up edits.

The fallback dict MIRRORS the JSON values byte-for-byte. If you change
a default in the JSON, update the fallback here too (otherwise the
"missing file" scenario silently drifts from "file present" semantics).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict


# ----------------------------------------------------------------------------
# Fallback / defaults — identical to thresholds.json (must stay in sync).
# Comment-keys ("_about", "_…") omitted here for brevity; they're optional
# documentation only.
# ----------------------------------------------------------------------------
FALLBACK: Dict[str, Dict[str, Any]] = {
    "brake": {
        "zone_threshold_fraction": 0.05,
        "zone_min_samples": 8,
        "build_low_frac": 0.10,
        "build_high_frac": 0.90,
        "build_good_seconds": 0.30,
        "build_warn_seconds": 0.60,
        "trail_corr_good": 0.4,
        "trail_corr_warn": 0.1,
        "smooth_pump_threshold_frac": 0.10,
        "apex_release_low_frac": 0.10,
        "apex_release_min_seconds": 0.2,
        "apex_release_requires_prior_peak_frac": 0.50,
        "apex_search_distance_m": 200,
    },
    "accel": {
        "phase_max_distance_m": 800,
        "phase_min_samples": 10,
        "sharp_drop_lookback_samples": 10,
        "sharp_drop_recent_max_min": 30,
        "sharp_drop_amount": 30,
        "full_throttle_threshold": 95,
        "ramp_good_seconds": 1.0,
        "ramp_warn_seconds": 2.0,
        "smooth_min_running_max": 20,
        "smooth_pump_drop_amount": 10,
        "straight_lean_max_deg": 10,
        "straight_min_samples": 5,
        "straight_good_pct": 0.80,
        "straight_warn_pct": 0.50,
        "error_marker_throttle_max": 90,
        "error_marker_min_seconds": 0.3,
    },
    "electronics": {
        "slip_ratio": 0.10,
        "slip_min_seconds": 0.10,
        "slip_gap_seconds": 0.05,
        "slip_min_ref_speed": 5,
        "spike_window_seconds": 0.15,
        "spike_rate_threshold": 30,
        "spike_continue_rate": 15,
        "spike_merge_seconds": 0.5,
        "osc_window_seconds": 0.25,
        "osc_min_mean": 5,
        "osc_threshold": 0.05,
        "osc_min_seconds": 0.30,
        "osc_gap_seconds": 0.10,
        "status_deviation": 0.5,
        "status_min_seconds": 0.05,
        "status_gap_seconds": 0.10,
    },
    "suspension_block": {
        "top_band_frac": 0.01,
        "plateau_flat_frac": 0.005,
        "plateau_min_seconds": 0.040,
        "gap_seconds": 0.020,
        "edge_window_seconds": 0.060,
        "edge_rise_frac": 0.20,
    },
    "suspension_topout": {
        "bottom_band_frac": 0.01,
        "plateau_flat_frac": 0.005,
        "plateau_min_seconds": 0.040,
        "gap_seconds": 0.020,
        "edge_window_seconds": 0.060,
        "edge_drop_frac": 0.20,
    },
    "suspension_bump": {
        "k_mad": 6.0,
        "safety_floor_mm_s": 200,
        "max_duration_seconds": 0.100,
        "merge_gap_seconds": 0.050,
    },
    "suspension_histogram": {
        "num_bins": 41,
        "outlier_quantile": 0.995,
        "safety_floor_frac": 0.1,
    },
}


# ----------------------------------------------------------------------------
# Loading + merging
# ----------------------------------------------------------------------------

def strip_comments(node: Any) -> Any:
    """Recursively strip keys starting with '_' from dicts.

    Used before serving thresholds to the browser — the JSON allows
    documentation keys ('_about', '_zone_threshold_fraction', …) but
    they're noise on the wire.
    """
    if isinstance(node, dict):
        return {k: strip_comments(v) for k, v in node.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(node, list):
        return [strip_comments(x) for x in node]
    return node


def merge_with_fallback(loaded: Dict[str, Any],
                        fallback: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user-provided dict on top of fallback.

    - Top-level sections present in fallback but missing in loaded → fallback.
    - Individual keys missing in a section → fallback value.
    - Extra keys in loaded → kept (forward-compat: lets Stefan add new
      thresholds without editing this module first).
    - Extra top-level sections in loaded → kept.
    - Type mismatch on a leaf → fallback value (defensive).
    """
    out: Dict[str, Any] = {}
    sections = set(fallback.keys()) | set(loaded.keys() if isinstance(loaded, dict) else [])
    for section in sections:
        fb_sect = fallback.get(section, {})
        ld_sect = loaded.get(section, {}) if isinstance(loaded, dict) else {}
        if not isinstance(ld_sect, dict):
            out[section] = fb_sect
            continue
        merged: Dict[str, Any] = {}
        keys = set(fb_sect.keys()) | set(ld_sect.keys())
        for key in keys:
            if key in ld_sect:
                lv = ld_sect[key]
                fv = fb_sect.get(key)
                # Type sanity: number-vs-number, otherwise fallback
                if fv is not None and not _types_compatible(lv, fv):
                    merged[key] = fv
                else:
                    merged[key] = lv
            else:
                merged[key] = fb_sect[key]
        out[section] = merged
    return out


def _types_compatible(a: Any, b: Any) -> bool:
    """Compatibility for leaf values. int/float interchangeable;
    everything else must match exact type. bool is NOT compatible
    with int (Python quirk: bool is-a int)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return True
    return type(a) is type(b)


def load(path: str) -> Dict[str, Any]:
    """Load thresholds from path, merging with FALLBACK.

    Best-effort: missing file, malformed JSON, wrong shape all yield
    the pure FALLBACK dict. Errors are silenced (the caller can detect
    "file used / fallback only" via the returned `source` indirectly,
    but right now we don't expose that)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return _deepcopy(FALLBACK)
        return merge_with_fallback(raw, FALLBACK)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _deepcopy(FALLBACK)


def _deepcopy(d: Dict[str, Any]) -> Dict[str, Any]:
    """Tiny deepcopy — avoids importing copy. Only handles dicts/lists/scalars."""
    if isinstance(d, dict):
        return {k: _deepcopy(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_deepcopy(x) for x in d]
    return d


# Lade die Datei (best-effort). Liegt im Repo-Root, neben diesem Modul.
_THRESHOLDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "thresholds.json")
THRESHOLDS: Dict[str, Any] = load(_THRESHOLDS_PATH)


def get_thresholds() -> Dict[str, Any]:
    """Return the currently loaded thresholds, with comment-keys stripped.

    Webserver uses this to embed thresholds into the coach page and
    serve them via /api/thresholds.
    """
    return strip_comments(THRESHOLDS)
