"""generic utilities"""
import datetime as dt
from inspect import signature
from typing import Callable

from vipersci.pds.datetime import isozformat


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


def get_argnames(func: Callable) -> set[str]:
    """reads the names of the arguments the function will accept"""
    return set(signature(func).parameters.keys())
