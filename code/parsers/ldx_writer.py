"""Writer for MoTeC i2 .ldx files.

Based on the proven-working format from GeekyDeaks/sim-to-motec.

The .ldx is XML accompanying a .ld file (same basename). It carries beacon
markers (= lap boundaries) and metadata.

CRITICAL: Beacon Time is in MICROSECONDS (not seconds), accumulated since
session start. Each marker has Version="100", ClassName="BCN", and Flags="77".

Structure:
    <?xml version="1.0" encoding="utf-8"?>
    <LDXFile locale="English_United Kingdom.1252" DefaultLocale="C" Version="1.6">
      <Layers>
        <Layer>
          <MarkerBlock>
            <MarkerGroup Name="Beacons" Index="N-1">  <!-- 0-indexed last marker -->
              <Marker Version="100" ClassName="BCN" Name="Manual.1" Flags="77" Time="123456.78"/>
              ...
            </MarkerGroup>
          </MarkerBlock>
        </Layer>
        <Details>
          <String Id="Total Laps" Value="..."/>
          <String Id="Fastest Time" Value="MM:SS.sss"/>
          <String Id="Fastest Lap" Value="N"/>
        </Details>
      </Layers>
    </LDXFile>
"""
from typing import Sequence, Optional, List
from xml.dom import minidom


def write_ldx(
    output_path: str,
    lap_times_s: Sequence[float],
    *,
    event: str = "",
    venue: str = "",
    driver: str = "",
    vehicle: str = "",
    session: str = "",
    log_date: str = "",
    log_time: str = "",
):
    """Write an .ldx file containing beacon markers for each lap.

    Args:
        output_path: target path (typically same basename as .ld but with .ldx)
        lap_times_s: list of lap durations in seconds. The Nth beacon marks
            the end of lap N (= start of lap N+1). Times are accumulated to
            produce absolute timestamps in microseconds, which is what i2 stores.
    """
    root = minidom.Document()
    ldx = root.createElement("LDXFile")
    root.appendChild(ldx)
    ldx.setAttribute("locale", "English_United Kingdom.1252")
    ldx.setAttribute("DefaultLocale", "C")
    ldx.setAttribute("Version", "1.6")

    layers = root.createElement("Layers")
    ldx.appendChild(layers)

    layer = root.createElement("Layer")
    layers.appendChild(layer)

    marker_block = root.createElement("MarkerBlock")
    layer.appendChild(marker_block)

    marker_group = root.createElement("MarkerGroup")
    marker_block.appendChild(marker_group)
    marker_group.setAttribute("Name", "Beacons")
    n_laps = len(lap_times_s)
    marker_group.setAttribute("Index", str(max(0, n_laps - 1)))

    # Accumulate times: beacon at end of lap i = sum of laps 1..i in microseconds
    elapsed_us = 0
    for lap_num, lap_time in enumerate(lap_times_s, start=1):
        elapsed_us += lap_time * 1_000_000  # seconds → microseconds
        marker = root.createElement("Marker")
        marker.setAttribute("Version", "100")
        marker.setAttribute("ClassName", "BCN")
        marker.setAttribute("Name", f"Manual.{lap_num}")
        marker.setAttribute("Flags", "77")
        marker.setAttribute("Time", f"{elapsed_us:0.2f}")
        marker_group.appendChild(marker)

    # Details section — fastest lap, total laps, etc.
    details = root.createElement("Details")
    layers.appendChild(details)

    def _add(key, value):
        if value is None or value == "":
            return
        el = root.createElement("String")
        details.appendChild(el)
        el.setAttribute("Id", key)
        el.setAttribute("Value", str(value))

    _add("Event", event)
    _add("Venue", venue)
    _add("Driver", driver)
    _add("Vehicle Id", vehicle)
    _add("Session", session)
    if log_date:
        el = root.createElement("DateTime")
        details.appendChild(el)
        el.setAttribute("Id", "Log Date")
        el.setAttribute("Value", log_date)
    if log_time:
        el = root.createElement("DateTime")
        details.appendChild(el)
        el.setAttribute("Id", "Log Time")
        el.setAttribute("Value", log_time)

    # Total Laps (include in-lap as +1 per GeekyDeaks)
    if n_laps > 0:
        _add("Total Laps", str(n_laps + 1))

    # Fastest lap (excluding outlap = first lap, per GeekyDeaks convention)
    if n_laps >= 2:
        candidates = list(enumerate(lap_times_s))[1:]  # skip outlap
        idx, t = min(candidates, key=lambda p: p[1])
        # idx is 0-based in original list; convert to 1-based lap number
        fastest_lap_num = idx + 1  # +1 because we skipped index 0 (outlap)
        # But actually: if outlap is laps[0], then candidates start at laps[1]
        # so idx=1 in the original list = lap 2 visually. We want to display
        # as the visible lap number. With outlap removed: idx 1 → lap 2.
        # GeekyDeaks does: fastestlap += 2 (which assumes 0-indexed candidate
        # then +1 for outlap removal +1 for 1-indexing).
        # Rewriting more clearly:
        minutes = int(t % 3600 // 60)
        seconds = t % 3600 % 60
        _add("Fastest Time", f"{minutes:02d}:{seconds:06.3f}")
        _add("Fastest Lap", str(fastest_lap_num + 1))  # 1-indexed
    elif n_laps == 1:
        t = lap_times_s[0]
        minutes = int(t % 3600 // 60)
        seconds = t % 3600 % 60
        _add("Fastest Time", f"{minutes:02d}:{seconds:06.3f}")
        _add("Fastest Lap", "1")

    xml_str = root.toprettyxml(indent="  ", encoding="utf-8")
    with open(output_path, "wb") as f:
        f.write(xml_str)
    return output_path
