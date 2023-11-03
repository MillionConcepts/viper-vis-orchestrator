"""utilities for the orchestrator application."""
import datetime as dt
import re
from collections import deque
from io import BytesIO
from pathlib import Path
from typing import Mapping, MutableSequence, Any, Optional

import dateutil.parser
import numpy as np
from PIL import Image
from cytoolz import itemfilter
from imageio.v3 import imread

from vipersci.pds.datetime import isozformat
from vipersci.vis.db.image_records import ImageRecord
from yamcs.tmtc.model import ParameterValue, ParameterData

from hostess.station.bases import NoMatch
from hostess.utilities import curry

IMAGERECORD_COLUMNS = frozenset(c.name for c in ImageRecord.__table__.columns)
UnpackedParameter = Mapping[str, Any]


def unpack_parameter_value(value: ParameterValue) -> UnpackedParameter:
    """unpack a yamcs ParameterValue object into a dictionary for easy use."""
    rec = {}
    for key in (
        'eng_value',
        'generation_time',
        'monitoring_result',
        'name',
        'processing_status',
        'range_condition',
        'raw_value',
        'reception_time',
        'validity_duration',
        'validity_status'
    ):
        rec[key] = getattr(value, key)
    return rec


def unpack_parameters(messages: ParameterData) -> list[UnpackedParameter]:
    """
    convert a ParameterData object (as returned by a yamcs subscription) into
    a list of unpacked parameter mappings.
    """
    return [unpack_parameter_value(value) for value in messages.parameters]


def convert_16bit_tif(
    inpath: Path,
    outpath: Path,
    size: Optional[tuple[int, int]] = None
):
    """
    open a 16-bit tiff file, make a thumbnail from it, write it back to disk.
    optionally also thumbnail it.
    """
    # noinspection PyTypeChecker
    im = np.asarray(Image.open(inpath))
    # PIL's built-in conversion for 16-bit integer images does bad things
    im = Image.fromarray(np.floor(im / 65531 * 255).astype(np.uint8))
    if size is not None:
        im.thumbnail(size)
    im.save(outpath)


def popleft(cache: deque) -> deque:
    """
    pop everything from a deque and return it as a reversed version of that
    deque
    """
    output = deque()
    while len(cache) > 0:
        output.append(cache.popleft())
    return output


@curry
def push(cache: MutableSequence, obj: Any):
    """curried push-to-cache function"""
    cache.append(obj)


def validate_pdict(pdict: UnpackedParameter):
    """
    checks that pdict appears to be an unpacked yamcs ParameterData object;
    raises NoMatch if not (intended to be used by an Actor's match() method)
    """
    if not isinstance(pdict, Mapping):
        raise NoMatch("this is not a dict")
    if "eng_value" not in pdict.keys():
        raise NoMatch("no eng_value key")


def temp_hardcoded_header_values():
    # These are hard-coded until we figure out where they come from.
    return {
        "bad_pixel_table_id": 0,
        "hazlight_aft_port_on": False,
        "hazlight_aft_starboard_on": False,
        "hazlight_center_port_on": False,
        "hazlight_center_starboard_on": False,
        "hazlight_fore_port_on": False,
        "hazlight_fore_starboard_on": False,
        "navlight_left_on": False,
        "navlight_right_on": False,
        "mission_phase": "TEST",
        "purpose": "Navigation",
    }


class NotAnImageParameter(ValueError):
    pass


def unpack_image_parameter_data(
    parameter: ParameterValue | UnpackedParameter
) -> tuple[dict, np.ndarray]:
    """preprocess a parameter value for use by create_image.create()."""
    if not isinstance(parameter, ParameterValue):
        get = parameter.__getitem__
    else:
        get = parameter.__getattribute__
    if len({"imageHeader", "imageData"} & get("eng_value").keys()) != 2:
        raise NotAnImageParameter
    parameter_dict = (
        {
            "yamcs_name": get("name"),
            "yamcs_generation_time": get("generation_time"),
        }
        | get("eng_value")["imageHeader"]
        | temp_hardcoded_header_values()
    )
    if isinstance(parameter, dict):
        # allows us to explicitly manipulate ImageRecord constructors
        parameter_dict |= itemfilter(
            lambda kv: kv[0] not in ("eng_value", "raw_value"), parameter
        )
    # parse dates expressed as strings into tz-aware dt.datetimes
    for k, v in parameter_dict.items():
        if isinstance(v, dt.datetime):
            parameter_dict[k] = v.astimezone(dt.UTC)
            continue
        if not isinstance(v, str):
            continue
        # parse dates expressed as strings into tz-aware dt.datetimes
        if isinstance(v, str) and re.match(r"20\d\d-\d\d-", v):
            parameter_dict[k] = dateutil.parser.parse(v).astimezone(dt.UTC)
    with BytesIO(get("eng_value")["imageData"]) as f:
        image: np.ndarray = imread(f)
    # filter parameters that can cause undefined behavior in ImageRecord
    for badkey in ("generation_time", "reception_time"):
        parameter_dict.pop(badkey, None)
    return parameter_dict, image


def utcnow():
    return dt.datetime.utcnow().replace(tzinfo=dt.UTC)


def stringify_timedict(timedict):
    stringified = {}
    for k, v in timedict.items():
        if isinstance(v, dt.datetime):
            stringified[k] = isozformat(v.astimezone(dt.UTC))
        else:
            stringified[k] = str(v)
    return stringified
