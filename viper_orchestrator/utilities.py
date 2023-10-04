"""generic utilities"""
import datetime as dt


def utcnow():
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
