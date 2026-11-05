"""Verify XRK fix — run on the user's server."""
import sys
sys.path.insert(0, '.')
from parsers.xrk_reader import parse_xrk

if len(sys.argv) < 2:
    print("Usage: python3 verify.py FILE.xrk")
    sys.exit(1)

t = parse_xrk(sys.argv[1])
print(f"Samples: {len(t['time'])}")
print(f"Time range: {t['time'][0]:.2f}s .. {t['time'][-1]:.2f}s (should start near 0)")
print(f"Lat range: {t['lat'].min():.4f}..{t['lat'].max():.4f}")
print(f"Lon range: {t['lon'].min():.4f}..{t['lon'].max():.4f}")
print(f"  (for Cremona: lat~45.08, lon~10.31)")
print(f"Speed range: {t['speed'].min():.1f}..{t['speed'].max():.1f} km/h")
print(f"Lap_times: {len(t['lap_times'])} laps")

# Now try a fastest-lap extraction
from laps import detect_laps, fastest_lap, extract_lap_data
laps = detect_laps(t)
fast = fastest_lap(laps)
print(f"\nFastest lap detected: Lap {fast['lap_index']}, duration {fast['duration']:.3f}s")
print(f"  Lap start_time: {fast['start_time']:.2f}s, end_time: {fast['end_time']:.2f}s")

lap_data = extract_lap_data(t, fast)
print(f"  Extracted samples: {len(lap_data['time'])}")
print(f"  Distance: {lap_data['distance'][-1]:.1f} m")
print(f"  Speed range: {lap_data['speed'].min():.1f}..{lap_data['speed'].max():.1f} km/h")

if len(lap_data['time']) > 100 and lap_data['distance'][-1] > 1000:
    print("\n✓ SUCCESS — graphs should render correctly now")
else:
    print("\n✗ STILL BROKEN — empty/short extraction")
