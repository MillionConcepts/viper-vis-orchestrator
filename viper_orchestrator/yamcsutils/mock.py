import datetime as dt
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from pathlib import Path
from random import shuffle
from typing import Literal, Any, Optional, Collection, Iterator, Callable

import pandas as pd
from cytoolz import get_in
from dustgoggles.structures import dig_and_edit, NestingDict
from pyarrow import parquet

from viper_orchestrator.yamcsutils.parameter_record_helpers import (
    cast_to_nullable_integer,
)


def _poll_ctx(cache, parameters, on_data, delay, signals, thread_id):
    """poll a cache representing a yamcs server websocket."""
    while True:
        if signals[thread_id] != 0:
            return
        for param in parameters:
            while len(cache[param]) > 0:
                event = cache[param].pop()
                on_data(event)
        time.sleep(delay)


class MockServer:
    """
    mock for the yamcs server, backed by a parquet file containing parameter
    data values and a folder of binary blobs.
    """

    def __init__(
        self,
        events="events.parquet",
        blobs_folder=Path(__file__).parent / "blobs/",
        mode: Literal[
            "no_replacement", "sequential", "replacement"
        ] = "sequential",
    ):
        # the parquet <-> pandas roundtrip converts some nan values to 'nan'
        self.source = (
            cast_to_nullable_integer(parquet.read_table(events).to_pandas())
            .replace("nan", float("nan"))
            .sort_values(by='generation_time')
            .reset_index(drop=True)
        )
        self.blobs_folder = blobs_folder
        self.log, self._parameters, self._pickable, = (
            [],
            None,
            self.source,
        )
        if mode not in ("no_replacement", "sequential", "replacement"):
            raise ValueError("unrecognized mode")
        self._pickable_indices, self.mode = None, mode

    def _pick_event(self, event_ix: Optional[int] = None) -> tuple[dict, int]:
        if event_ix is not None:
            ix = event_ix
        else:
            if self.mode in ("replacement", "no_replacement"):
                shuffle(self._pickable_indices)
            if self.mode in ("no_replacement", "sequential"):
                ix = self._pickable_indices.pop()
            else:
                ix = self._pickable_indices[0]
        try:
            record = self._pdict[ix]
        except IndexError:
            raise IndexError("event_ix not in pickable indices")
        self.log.append((record['name'], record['generation_time'], ix))
        return record, ix

    def _get_event_range(
        self,
        parameters: Collection[str],
        start: Optional[dt.datetime] = None,
        stop: Optional[dt.datetime] = None
    ) -> pd.DataFrame:
        rangeslice = self.source
        if start is not None:
            rangeslice = rangeslice.loc[rangeslice['generation_time'] > start]
        if stop is not None:
            rangeslice = rangeslice[rangeslice['generation_time'] < stop]
        return rangeslice.loc[rangeslice['name'].isin(parameters)]

    def _set_parameters(self, parameters):
        self._parameters = parameters
        if self._parameters is None:
            self._pickable = self.source
        else:
            self._pickable = self.source.loc[
                self.source["name"].isin(self._parameters)
            ]
        self._pickable_indices = list(reversed(self._pickable.index))
        self._pdict = self._pickable.to_dict('index')

    def _get_parameters(self):
        return self._parameters

    # noinspection PyTypeChecker
    def _create_structure(
        self, record: dict, ix: int, **fields
    ) -> NestingDict:
        record = {k: v for k, v in record.items() if not pd.isna(k)}
        # add/overwrite requested keys first
        record |= fields
        # now re-nest the unnested values
        event = NestingDict()
        for key in record.keys():
            if "eng_value_" in key:
                put_into_dict(key, event["eng_value"], record)
            elif "raw_value_" in key:
                put_into_dict(key, event["raw_value"], record)
            elif not any(
                val in key for val in ("eng_value", "raw_value", "pivot")
            ):
                event[key] = record[key]
        for data_type in ("eng", "raw"):
            if record[f"{data_type}_value"] not in ("unnested", None, "None"):
                assert f"{data_type}_value" not in event.keys()
                event[f"{data_type}_value"] = record[f"{data_type}_value"]
            elif record["pivot"] is True:
                event = self._add_blob(event, data_type, ix)
        return dig_and_edit(
            event,
            filter_func=lambda _, v: isinstance(v, pd.Timestamp),
            setter_func=lambda _, v: v.to_pydatetime(),
            mtypes=(dict, NestingDict)
        )

    def _add_blob(
        self, event: NestingDict, data_type: Literal["eng", "raw"], ix: int
    ) -> NestingDict[str, Any]:
        matches = filter(
            lambda p: p.name.startswith(f"pivot_{ix}_{data_type}"),
            self.blobs_folder.iterdir(),
        )
        blob_file = next(matches)
        blob = blob_file.read_bytes()
        if "imageData" in blob_file.name:
            event["eng_value"]["imageData"] = blob
        else:
            event["eng_value"] = blob
        return event

    def get_from_archive(
        self,
        parameters: Collection[str],
        start: Optional[dt.datetime] = None,
        stop: Optional[dt.datetime] = None,
        **fields
    ) -> Iterator[NestingDict[str, Any]]:
        """
        return an iterator of NestingDicts structured like 'unpacked' yamcs
        ParameterData.
        """
        range_df = self._get_event_range(parameters, start, stop)
        # noinspection PyTypeChecker
        return iter(
            self._create_structure(self._pickable[ix], ix, **fields)
            for ix in range_df.index
        )

    def serve_event(
        self,
        event_ix: Optional[int] = None,
        **fields
    ) -> NestingDict[str, Any]:
        """
        return a NestingDict structured like 'unpacked' yamcs ParameterData.
        """
        record, ix = self._pick_event(event_ix)
        event = self._create_structure(record, ix, **fields)
        return event

    def serve_to_ctx(self, event_ix=None, **fields):
        """
        serve a NestingDict structured like 'unpacked' yamcs ParameterData into
        self.ctx
        """
        if self.ctx is None:
            raise ValueError(".ctx attribute not assigned")
        event = self.serve_event(event_ix, **fields)
        self.ctx[event["name"]].append(event)

    @property
    def start_time(self):
        return self.source['generation_time'].min().to_pydatetime()

    @property
    def stop_time(self):
        return self.source['generation_time'].max().to_pydatetime()

    parameters = property(_get_parameters, _set_parameters)
    ctx = None


class MockContext:
    """
    mock for a collection of 'under the hood' objects yamcs-client uses to
    manage connections to the yamcs server.

    it is basically a mock non-blocking websocket represented by a
    thread pool and a dictionary. this does not support
    multiple subscriptions to the same parameters in a single
    process, which we would never want to do anyway: the cache
    is intentionally volatile.
    """

    def __init__(self, cache=None, n_threads=4):
        self.exec = ThreadPoolExecutor(n_threads)
        if cache is None:
            self.cache = defaultdict(list)
        self._signals = {}
        self._counter = count()

    def __getitem__(self, key):
        return self.cache[key]

    def __setitem__(self, key, value):
        self.cache[key] = value

    def run(self, parameters, on_data, delay):
        thread_id = next(self._counter)
        self._signals[thread_id] = 0
        manager = self.exec.submit(
            _poll_ctx,
            self.cache,
            parameters,
            on_data,
            delay,
            self._signals,
            thread_id,
        )
        return manager, thread_id

    def addevent(self, param, event):
        self[param].append(event)

    def kill(self):
        for thread_id in self._signals.keys():
            self._signals[thread_id] = 1
        self.exec.shutdown(wait=False, cancel_futures=True)

    def cancel(self, thread_id):
        self._signals[thread_id] = 1


class MockYamcsClient:
    """mock for yamcs-client Client object"""

    def __init__(
        self,
        ctx: Optional[MockContext] = None,
        server: Optional[MockServer] = None
    ):
        if ctx is None and server is None:
            raise TypeError("either ctx or server must be defined")
        self.ctx = ctx
        self.server = server

    def get_processor(self, instance, processor) -> "MockYamcsProcessor":
        if self.ctx is None:
            raise TypeError("must have self.ctx to generate a processor")
        return MockYamcsProcessor(self, instance, processor, self.ctx)

    def get_archive(self, instance) -> "MockArchive":
        if self.server is None:
            raise TypeError("must have self.server to generate an archive")
        return MockArchive(self, instance, self.server)


class MockArchive:
    """
    mock for yamcs-client ArchiveClient object.
    note that the archive interface is 'pull' rather than 'push', so it needs
    a direct reference to the mock server rather than to a mock websocket.
    """

    def __init__(
        self,
        client: MockYamcsClient,
        instance: str,
        server: MockServer
    ):
        self.instance = instance
        self.server = server
        self.client = client

    def stream_parameter_values(
        self,
        parameters: Collection[str],
        start: Optional[dt.datetime] = None,
        stop: Optional[dt.datetime] = None,
        **fields
    ) -> Iterator[NestingDict[str, Any]]:
        return self.server.get_from_archive(
            parameters, start=start, stop=stop, **fields
        )

    def list_parameter_values(
        self,
        parameter: str,
        start: Optional[dt.datetime] = None,
        stop: Optional[dt.datetime] = None,
        **fields
    ) -> Iterator[NestingDict[str, Any]]:
        return self.server.get_from_archive(
            (parameter,), start=start, stop=stop, **fields
        )
# overloading the term "processor" is v. confusing IMO, but I'm
# following their naming structure.


class MockYamcsProcessor:
    """mock for yamcs-client Processor object"""

    def __init__(
        self,
        client: MockYamcsClient,
        instance: str,
        processor: str,
        ctx: MockContext
    ):
        self.instance = instance
        self.processor = processor
        self.ctx = ctx
        self.client = client

    def create_parameter_subscription(
        self,
        parameters: Collection[str],
        on_data: Callable
    ) -> "MockSubscription":
        return MockSubscription(parameters, on_data, self, self.ctx)


class MockSubscription:
    """mock for yamcs-client Subscription object"""

    def __init__(
        self,
        parameters: Collection[str],
        on_data: Callable[[NestingDict], None],
        yamcs_processor: MockYamcsProcessor,
        ctx: MockContext,
        delay: float = 0.1
    ):
        if isinstance(parameters, str):
            raise TypeError("parameters must be a collection of str")
        self.parameters = parameters
        self.yamcs_processor = yamcs_processor
        self.ctx = ctx
        self.callback = on_data
        # mock version of WebSocketSubscriptionManager functionality
        self._manager, self.thread_id = ctx.run(parameters, on_data, delay)

    def cancel(self):
        self.ctx.cancel(self.thread_id)
        return self._manager.cancel()

    def running(self):
        return self._manager.running()


def test_mock_client():
    ctx = MockContext()
    client = MockYamcsClient(ctx)
    processor = client.get_processor("viper", "realtime")
    read_cache = []
    sub = processor.create_parameter_subscription(
        ["/Fake/parameter"], lambda a: read_cache.append(a)
    )
    time.sleep(0.1)
    assert sub.running()
    ctx.addevent("/Fake/parameter", 1)
    time.sleep(0.2)
    assert read_cache.pop() == 1
    ctx.kill()


def put_into_dict(key, top_level_dict, record):
    list_of_keys = key.split("_value_")[1].split("_")
    target_dict = get_in(list_of_keys[:-1], top_level_dict)
    target_dict[list_of_keys[-1]] = record[key]
