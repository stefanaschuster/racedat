"""File parsers and writers for race-data formats."""
from .ses_parser import parse_ses
from .ld_parser import parse_ld
from .racebox_parser import parse_racebox_csv
from .aim_csv_parser import parse_aim_csv, is_aim_csv
from .starlane_csv_parser import parse_starlane_csv, is_starlane_csv
from .i2m_parser import parse_i2m
from .d2_parser import parse_2d
from . import ld_writer
from . import ldx_writer

# XRK reader requires the AiM DLL. Import lazily to avoid blocking
# the rest of the toolchain if the DLL isn't installed.
def parse_xrk(*args, **kwargs):
    """Wrapper around xrk_reader.parse_xrk; deferred import."""
    from .xrk_reader import parse_xrk as _impl
    return _impl(*args, **kwargs)

__all__ = ["parse_ses", "parse_ld", "parse_xrk", "parse_racebox_csv",
           "parse_aim_csv", "is_aim_csv",
           "parse_starlane_csv", "is_starlane_csv",
           "parse_i2m", "parse_2d", "ld_writer", "ldx_writer"]
