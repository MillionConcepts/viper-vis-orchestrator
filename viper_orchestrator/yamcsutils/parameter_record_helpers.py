"""
utilities for reading and reformatting parameter records. used to construct
the contents of the mock_events* folders used by mock_yamcs.MockServer.
"""
from collections import OrderedDict
import datetime as dt
from pathlib import Path
from typing import Union, Collection

from dustgoggles.pivot import numeric_columns
from dustgoggles.structures import NestingDict, unnest
import numpy as np
import pandas as pd
import pyarrow as pa
from pyarrow import parquet

# 'validity_status' is 'ACQUIRED' for everything in the cache
# 'processing_status' is False
# 'range_condition' is None
# 'validity_duration' is None
# 'monitoring_result' is None.
# TODO: revisit these when we get a new set of sample data.
BORING_KEYS = (
    "monitoring_result",
    "processing_status",
    "range_condition",
    "validity_duration",
    "validity_status",
)


def unpack_pickled_parameters(pickle_file: Union[str, Path]) -> pd.DataFrame:
    """
    unpack parameters from a pickle file written by the packetreader utilities
    """
    records = pd.read_pickle(pickle_file)
    if not isinstance(records, list):
        cache = []
        for rec in records:
            cache += rec.pop("cache")
    else:
        cache = records
    del records
    processed = []
    for rec in cache:
        procrec = {}
        for k, v in rec.items():
            if k in BORING_KEYS:
                continue
            if isinstance(v, OrderedDict):
                procrec |= {f"{k}_{uk}": uv for uk, uv in unnest(v).items()}
                procrec[k] = "unnested"
            elif isinstance(v, (float, str, int, bytes)):
                procrec[k] = v
            elif isinstance(v, dt.datetime):
                # procrec[k] = v.isoformat()
                procrec[k] = v
            else:
                raise TypeError("hmmm...what is this")
        processed.append(procrec)
    return pd.DataFrame(processed)


def make_dtype_defs(df: pd.DataFrame) -> pd.DataFrame:
    """
    make df of appropriate dtypes for passed DataFrame. kind of ugly but works
    """
    num = numeric_columns(df)
    rangedef = NestingDict()
    for k, v in num.items():
        dropped = v.dropna()
        offset = (dropped.astype(int) - dropped).abs().max()
        if offset == 0:
            rangedef[k]["integer"] = True
        else:
            rangedef[k]["integer"] = offset
        rangedef[k]["ptp"] = np.ptp(dropped)
        rangedef[k]["max"] = dropped.abs().max()
        rangedef[k]["signed"] = dropped.min() < 0
    defs = pd.DataFrame(rangedef).T
    defs["dtype"] = None
    defs["pa_dtype"] = None
    ipred = defs["integer"] == True
    assert not defs.loc[ipred, "signed"].any()
    # TODO: ugly
    defs.loc[(defs["max"] > 2147483647) & ipred, "dtype"] = pd.Int64Dtype()
    defs.loc[(defs["max"] <= 2147483647) & ipred, "dtype"] = pd.Int32Dtype()
    defs.loc[(defs["max"] <= 32767) & ipred, "dtype"] = pd.Int16Dtype()
    defs.loc[(defs["max"] <= 4294967295) & ipred, "pa_dtype"] = pa.uint32()
    defs.loc[(defs["max"] <= 65535) & ipred, "pa_dtype"] = pa.uint16()
    defs.loc[(defs["max"] <= 255) & ipred, "pa_dtype"] = pa.uint8()
    defs.loc[(defs["max"] <= 3.4028235e38) & ~ipred, "dtype"] = np.float32
    defs.loc[(defs["max"] <= 3.4028235e38) & ~ipred, "pa_dtype"] = pa.float32()
    defs.loc[(defs["max"] > 3.4028235e38) & ~ipred, "dtype"] = np.float64
    defs.loc[(defs["max"] > 3.4028235e38) & ~ipred, "pa_dtype"] = pa.float64()
    assert not defs["dtype"].isna().any()
    assert not defs["pa_dtype"].isna().any()
    return defs


def cast_to_nullable_integer(df: pd.DataFrame) -> pd.DataFrame:
    """
    downcast fields of DataFrame as appropriate, including converting integers
    to pandas nullable integers. pre/postprocessing for parquet roundtrip.
    """
    defs = make_dtype_defs(df)
    new_series = {}
    for k, v in df.items():
        if (k not in defs.index) or (defs.loc[k, "integer"] != True):
            new_series[k] = v
            continue
        new_series[k] = v.astype(defs.loc[k, "dtype"])
    return pd.DataFrame(new_series)


def pivot_blobs(
    rec_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    # todo: num construction is goofily inefficient,
    #  set dry-type option in dustgoggles
    bytefields, num = [], numeric_columns(rec_df)
    others = [f for f in rec_df if f not in num]
    del num
    for f in others:
        if "bytes" in set(map(lambda v: type(v).__name__, rec_df[f])):
            bytefields.append(f)
    byte_indices = set()
    for c in bytefields:
        byte_indices.update(
            rec_df.loc[rec_df[c].map(lambda v: isinstance(v, bytes))].index
        )
    byte_indices = list(byte_indices)
    bytevals = rec_df.loc[byte_indices].copy()
    rec_df.loc[byte_indices, bytefields] = None
    rec_df["pivot"] = False
    rec_df.loc[byte_indices, "pivot"] = True
    good_cols = rec_df.columns[~rec_df.isna().all(axis=0)]
    rec_df = rec_df[good_cols].copy()
    good_bytecols = bytevals.columns[~bytevals.isna().all(axis=0)]
    bytevals = bytevals[good_bytecols].copy()
    return rec_df, bytevals, bytefields


def write_parquet_and_blobs(
    rec_df: pd.DataFrame,
    bytevals: pd.DataFrame,
    bytefields: Collection[str],
    outpath: Union[str, Path] = ".",
):
    outpath = Path(outpath)
    defs = make_dtype_defs(numeric_columns(rec_df))
    fields = [
        pa.field(k, defs.loc[k, "pa_dtype"], True)
        for k, v in defs["dtype"].items()
    ]
    others = [f for f in rec_df if f not in defs.index]
    for f in others:
        if f == "pivot":
            rec_df[f] = rec_df[f].astype(bool)
            fields.append(pa.field(f, pa.bool_(), False))
        elif f == 'generation_time':
            fields.append(
                pa.field(f, pa.timestamp('ns', tz=rec_df.dtypes[f].tz))
            )
        else:
            rec_df[f] = rec_df[f].astype(str)
            fields.append(pa.field(f, pa.string(), True))
    arrays = []
    for field in fields:
        arrays.append(pa.array(rec_df[field.name], field.type))
    schema = pa.schema(fields)
    Path(outpath, "blobs").mkdir(exist_ok=True, parents=True)
    for ix, row in bytevals.iterrows():
        for bytefield in bytefields:
            if pd.isna(row[bytefield]):
                continue
            if row[bytefield] == "unnested":
                continue
            with Path(outpath, "blobs", f"pivot_{ix}_{bytefield}").open(
                "wb"
            ) as file:
                file.write(row[bytefield])
    # noinspection PyArgumentList
    rec_table = pa.Table.from_arrays(arrays, schema=schema)
    # TODO: metadata?
    parquet.write_table(rec_table, Path(outpath, "events.parquet"))
