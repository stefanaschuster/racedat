"""Writer for MoTeC i2 .ld telemetry files.

Based on the proven-working layout from GeekyDeaks/sim-to-motec
(github.com/GeekyDeaks/sim-to-motec) which produces files MoTeC i2 accepts,
with channel decoding cross-referenced against gotzl/ldparser.

Critical magic values that MoTeC i2 verifies:
  id     = 64           (file marker)
  sig1   = 1000000      (signature 1)
  sig2   = 128          (signature 2)
  type   = "ADL"        (device type)
  version= 420          (device version)

Channel datatype encoding (gotzl wire format):
  dtype_a = 0x03 (int16), 0x05 (int32), 0x07 (float)
  dtype   = byte size (2 or 4)
Channel id in meta record = 0x2EE1 + channel_index.

Sample value transformation:
  Real value:  real = (raw / scale * 10^(-dec) + shift) * mul
  Raw stored:  raw  = ((real / mul) - shift) * scale * 10^(dec)
"""
import struct
from typing import List, Optional, Sequence
import numpy as np


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

LD_HEADER_FMT = (
    '<'
    'I'      # +0    id (magic = 64)
    '4s'     # +4    pad
    'I'      # +8    firstchannelpos
    'I'      # +12   firstchanneldatapos
    '20s'    # +16   pad
    'I'      # +36   eventpos
    '26s'    # +40   pad
    'I'      # +66   sig1 = 1000000
    'I'      # +70   serial
    '8s'     # +74   type = "ADL"
    'H'      # +82   version = 420
    'H'      # +84   sig2 = 128
    'I'      # +86   numchannels
    '4s'     # +90   pad
    '16s'    # +94   date
    '16s'    # +110  pad
    '16s'    # +126  time
    '16s'    # +142  pad
    '64s'    # +158  driver
    '64s'    # +222  vehicle
    '64s'    # +286  pad
    '64s'    # +350  venue
    '1088s'  # +414  pad
    '4s'     # +1502 pad
    '66s'    # +1506 pad
    '64s'    # +1572 comment
    '126s'   # +1636 pad
)
LD_HEADER_SIZE = struct.calcsize(LD_HEADER_FMT)
assert LD_HEADER_SIZE == 1762, f"got {LD_HEADER_SIZE}"

EVENT_FMT = '<64s 64s 1024s H'
EVENT_SIZE = struct.calcsize(EVENT_FMT)
assert EVENT_SIZE == 1154

CHANNEL_FMT = (
    '<'
    'I'      # prev_meta_ptr
    'I'      # next_meta_ptr
    'I'      # data_ptr
    'I'      # data_len (n samples)
    'H'      # id (= 0x2EE1 + n)
    'H'      # datatype_a (0x03/0x05/0x07)
    'H'      # datatype (bytes per sample)
    'H'      # freq (sample rate Hz)
    'h'      # shift
    'h'      # mul
    'h'      # scale
    'h'      # dec
    '32s'    # name
    '8s'     # short_name
    '12s'    # unit
    '40s'    # pad
)
CHANNEL_SIZE = struct.calcsize(CHANNEL_FMT)
assert CHANNEL_SIZE == 124

DTA_INT16 = 0x03
DTA_INT32 = 0x05
DTA_FLOAT = 0x07

# Magic values — using GeekyDeaks/sim-to-motec defaults which are
# empirically proven to produce i2-readable files. Real MoTeC C125 files
# use type="C125", version=640, sig2=0 — both work.
DEFAULT_ID = 64
DEFAULT_SIG1 = 1_000_000
DEFAULT_SIG2 = 128
DEFAULT_TYPE = "ADL"
DEFAULT_VERSION = 420
DEFAULT_SERIAL = 12007
CHANNEL_ID_BASE = 0x2EE1


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class LDChannel:
    """One channel for an .ld file. `data` holds physical (real-world) values."""

    __slots__ = ("name", "short_name", "unit", "freq", "data",
                 "datatype_a", "data_size",
                 "shift", "mul", "scale", "dec")

    def __init__(self, name: str, unit: str, freq: int, data: np.ndarray, *,
                 short_name: Optional[str] = None,
                 datatype_a: int = DTA_INT16,
                 data_size: int = 2,
                 shift: int = 0, mul: int = 1, scale: int = 1, dec: int = 0):
        self.name = name
        self.short_name = short_name or name[:8]
        self.unit = unit
        self.freq = int(freq)
        self.data = np.asarray(data, dtype=np.float64)
        self.datatype_a = datatype_a
        self.data_size = data_size
        self.shift = shift
        self.mul = mul
        self.scale = scale
        self.dec = dec

    @property
    def numsamples(self) -> int:
        return len(self.data)

    @property
    def data_bytes(self) -> int:
        return self.numsamples * self.data_size

    def encode(self) -> bytes:
        if self.mul == 0:
            raise ValueError(f"Channel {self.name}: mul cannot be 0")
        # raw = ((real / mul) - shift) * scale * 10^dec
        scaled = ((self.data / self.mul) - self.shift) * self.scale * (10 ** self.dec)
        if self.datatype_a == DTA_INT16:
            arr = np.clip(np.round(scaled), -32768, 32767).astype('<i2')
        elif self.datatype_a == DTA_INT32:
            arr = np.clip(np.round(scaled),
                          -2_147_483_648, 2_147_483_647).astype('<i4')
        elif self.datatype_a == DTA_FLOAT:
            arr = self.data.astype('<f2' if self.data_size == 2 else '<f4')
        else:
            raise ValueError(f"Unsupported datatype_a: {self.datatype_a}")
        return arr.tobytes()


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def gps_lat_channel(lat_deg: np.ndarray, freq: int) -> LDChannel:
    return LDChannel("GPS Latitude", "deg", freq, lat_deg,
                     short_name="GPS Lat",
                     datatype_a=DTA_INT32, data_size=4, dec=7)


def gps_lon_channel(lon_deg: np.ndarray, freq: int) -> LDChannel:
    return LDChannel("GPS Longitude", "deg", freq, lon_deg,
                     short_name="GPS Lon",
                     datatype_a=DTA_INT32, data_size=4, dec=7)


def gps_speed_channel(speed_kmh: np.ndarray, freq: int) -> LDChannel:
    return LDChannel("GPS Speed", "km/h", freq, speed_kmh,
                     short_name="GPS Spd",
                     datatype_a=DTA_INT16, data_size=2, dec=1)


def battery_channel(volts: np.ndarray, freq: int) -> LDChannel:
    return LDChannel("Battery Voltage", "V", freq, volts,
                     short_name="Bat",
                     datatype_a=DTA_INT16, data_size=2, dec=2)


def beacon_channel(n_samples: int, freq: int,
                   lap_starts_idx: Sequence[int]) -> LDChannel:
    arr = np.zeros(n_samples, dtype=np.float64)
    for idx in lap_starts_idx:
        if 0 <= idx < n_samples:
            arr[idx] = 1.0
    return LDChannel("Beacon", "", freq, arr,
                     short_name="Beacon",
                     datatype_a=DTA_INT16, data_size=2, dec=0)


def running_lap_time_channel(time_arr: np.ndarray, beacon_times: Sequence[float],
                             freq: int) -> LDChannel:
    import bisect
    rlt = np.zeros_like(time_arr, dtype=np.float64)
    sorted_b = sorted(beacon_times)
    if not sorted_b:
        rlt = time_arr - time_arr[0]
    else:
        for i, t in enumerate(time_arr):
            idx = bisect.bisect_right(sorted_b, t) - 1
            if idx < 0:
                rlt[i] = t - time_arr[0]
            else:
                rlt[i] = t - sorted_b[idx]
    return LDChannel("Running Lap Time", "s", freq, rlt,
                     short_name="LapTime",
                     datatype_a=DTA_INT16, data_size=2, dec=2)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _zpad(s: str, length: int) -> bytes:
    b = s.encode('latin-1', errors='replace')[:length]
    return b + b'\x00' * (length - len(b))


def write_ld(
    output_path: str,
    channels: List[LDChannel],
    *,
    driver: str = "",
    vehicle: str = "",
    venue: str = "",
    event_name: str = "",
    session: str = "",
    comment: str = "",
    event_comment: str = "",
    date: str = "01/01/2000",
    time: str = "00:00:00",
    serial: int = DEFAULT_SERIAL,
):
    """Write an .ld file from a list of LDChannel objects."""
    if not channels:
        raise ValueError("At least one channel is required")

    eventpos = LD_HEADER_SIZE
    firstchannelpos = eventpos + EVENT_SIZE
    firstchanneldatapos = firstchannelpos + CHANNEL_SIZE * len(channels)

    data_offsets = []
    cur = firstchanneldatapos
    for ch in channels:
        data_offsets.append(cur)
        cur += ch.data_bytes

    ld_header = struct.pack(
        LD_HEADER_FMT,
        DEFAULT_ID,
        b'',
        firstchannelpos,
        firstchanneldatapos,
        b'',
        eventpos,
        b'',
        DEFAULT_SIG1,
        serial,
        _zpad(DEFAULT_TYPE, 8),
        DEFAULT_VERSION,
        DEFAULT_SIG2,
        len(channels),
        b'',
        _zpad(date, 16),
        b'',
        _zpad(time, 16),
        b'',
        _zpad(driver, 64),
        _zpad(vehicle, 64),
        b'',
        _zpad(venue, 64),
        b'',
        b'',
        b'',
        _zpad(comment, 64),
        b'',
    )
    assert len(ld_header) == LD_HEADER_SIZE

    event_block = struct.pack(
        EVENT_FMT,
        _zpad(event_name, 64),
        _zpad(session, 64),
        _zpad(event_comment, 1024),
        0,
    )

    channel_metas = []
    for i, ch in enumerate(channels):
        prev_ptr = firstchannelpos + (i - 1) * CHANNEL_SIZE if i > 0 else 0
        next_ptr = (firstchannelpos + (i + 1) * CHANNEL_SIZE
                    if i < len(channels) - 1 else 0)

        # Sanity-check ushort fields. Clamp rather than crash with cryptic
        # struct.error: ushort format requires 0 <= number <= 65535.
        ch_id = (CHANNEL_ID_BASE + i) & 0xFFFF
        ch_freq = max(1, min(65535, int(ch.freq)))
        ch_dtype_a = max(0, min(65535, int(ch.datatype_a)))
        ch_data_size = max(0, min(65535, int(ch.data_size)))
        # signed h fields: -32768..32767
        def _clip_h(v, name=""):
            if v < -32768 or v > 32767:
                import sys
                print(f"  [ld_writer] WARN: channel '{ch.name}' {name}={v} out of int16 range; clipping",
                      file=sys.stderr)
                return max(-32768, min(32767, int(v)))
            return int(v)
        ch_shift = _clip_h(ch.shift, "shift")
        ch_mul = _clip_h(ch.mul, "mul")
        ch_scale = _clip_h(ch.scale, "scale")
        ch_dec = _clip_h(ch.dec, "dec")

        if ch_freq != int(ch.freq):
            import sys
            print(f"  [ld_writer] WARN: channel '{ch.name}' freq={ch.freq} clipped to {ch_freq}",
                  file=sys.stderr)

        channel_metas.append(struct.pack(
            CHANNEL_FMT,
            prev_ptr, next_ptr,
            data_offsets[i], ch.numsamples,
            ch_id,
            ch_dtype_a,
            ch_data_size,
            ch_freq,
            ch_shift,
            ch_mul,
            ch_scale,
            ch_dec,
            _zpad(ch.name, 32),
            _zpad(ch.short_name, 8),
            _zpad(ch.unit, 12),
            b'',
        ))

    sample_blocks = [ch.encode() for ch in channels]

    with open(output_path, 'wb') as f:
        f.write(ld_header)
        assert f.tell() == eventpos
        f.write(event_block)
        assert f.tell() == firstchannelpos
        for blk in channel_metas:
            f.write(blk)
        assert f.tell() == firstchanneldatapos
        for blk in sample_blocks:
            f.write(blk)

    return output_path
