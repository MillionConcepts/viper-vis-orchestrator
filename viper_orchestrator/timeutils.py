"""generic utilities"""
import datetime as dt

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
