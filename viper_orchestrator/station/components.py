"""
Sensors, Actors, and Message constructors for the orchestrator application
"""
import datetime as dt
from abc import ABC
from collections import deque, defaultdict
from itertools import chain
from pathlib import Path
from typing import (
    Any,
    Collection,
    Optional,
    Mapping,
)

from dustgoggles.structures import listify
from google.protobuf.message import Message
from sqlalchemy import (
    Integer,
    ForeignKey,
    Identity, select,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column
from viper_orchestrator.station.utilities import (
    UnpackedParameter,
    unpack_parameters,
    popleft,
    push,
    validate_pdict,
    unpack_image_parameter_data,
)
from yamcs.client import YamcsClient

from hostess.station.actors import reported
from hostess.station.bases import (
    Actor,
    Node,
    Sensor,
    DoNotUnderstand,
    NoMatch,
)
from hostess.station.messages import (
    unpack_obj,
    make_function_call_action,
    make_instruction,
    make_action,
    pack_obj,
)
from hostess.station.proto import station_pb2 as pro
from viper_orchestrator.config import BROWSE_ROOT
from viper_orchestrator.db import OSession
from viper_orchestrator.timeutils import stringify_timedict
from viper_orchestrator.yamcsutils.mock import MockYamcsClient, MockContext
from vipersci.pds.pid import VISID
from vipersci.vis import create_image
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_stats import ImageStats
from vipersci.vis.db.light_records import luminaire_names, LightRecord

# noinspection PyTypeChecker


def process_image_instruction(note: UnpackedParameter) -> pro.Action:
    """
    convert a mapping constructed from an unpacked ParameterValue into an
    Action message specifying an image processing task.
    """
    instrument = VISID.instrument_name(
        note["data"]["eng_value"]["imageHeader"]["cameraId"]
    )
    timestamp = dt.datetime.fromtimestamp(
        note["data"]["eng_value"]["imageHeader"]["lobt"], tz=dt.UTC
    )
    action = make_action(
        name="process_image",
        localcall=pack_obj(note["data"]),
        description={"title": f"{instrument} {timestamp}"},
    )
    return make_instruction("do", action=action)


def thumbnail_instruction(note: Mapping[str, Any]) -> pro.Action:
    """
    convert a report of a newly-published image into an Action message
    specifying a thumbnailing task.
    """
    action = make_function_call_action(
        func="thumbnail_16bit_tif",
        module="viper_orchestrator.station.utilities",
        kwargs={
            "inpath": Path(note["content"]),
            "outpath": BROWSE_ROOT
            / Path(note["content"]).name.replace(".tif", "_thumb.jpg"),
        },
        context="process",
        description={"title": Path(note["content"]).name},
    )
    return make_instruction("do", action=action)


class ImageCheck(Actor):
    """
    checks whether a dict constructed from a yamcs parameter contains a
    serialized image and constructs an actionable event if so.
    """

    def match(self, pdict: dict, **_):
        try:
            validate_pdict(pdict)
            if not isinstance(pdict["eng_value"]["imageData"], bytes):
                raise NoMatch("imageData is not a bytestring")
            return True
        except Exception as ex:
            self.owner.owner._log("parameter match failed", exception=ex)

    def execute(self, node: Node, pdict: dict, **_):
        node.add_actionable_event(
            {
                "data": pdict,
                "parameter": pdict["name"],
                "event_type": "image_published",
            },
            self.owner,
        )

    actortype = "action"
    name = "imagecheck"


def get_light_state(
    at_time: Optional[dt.datetime] = None
) -> dict[str, bool]:
    """
    make dict representing light state immediately prior to at_time (or just
    the most recent light state if at_time is None).
    If no LightRecord available for a luminaire, it is set to False (off).
    """
    lightstate, gentime = {}, None
    for name in luminaire_names.keys():
        selector = select(LightRecord).where(LightRecord.name == name)
        if at_time is not None:
            selector = selector.where(LightRecord.datetime < at_time)
        selector = selector.order_by(LightRecord.datetime.desc())
        with OSession() as session:
            record = session.scalars(selector).first()
            if record is None:
                lightstate[name] = False
            else:
                lightstate[name] = record.on
                if gentime is None or gentime < record.datetime:
                    gentime = record.datetime
        lightstate[name] = False if record is None else record.on
    return lightstate | {'generation_time': gentime}


class LightStateProcessor(Actor):
    """
    actor that makes LightRecord objects from light state parameters.
    intended to be attached to a LightSensor.
    """

    def match(self, pdict: dict, **_) -> bool:
        validate_pdict(pdict)
        if pdict["name"] != "/ViperRover/LightsControl/state":
            raise NoMatch("not a light state parameter value")
        return True

    def execute(self, node: Node, light_pv: dict, **_):
        if self.owner.lightmem is None:
            return
        gentime = light_pv["generation_time"].astimezone(dt.UTC)
        # holding light state in memory is an optimization, but it is possible
        # for parameter values to arrive out of order. to avoid race
        # conditions, if we get an out-of-order value, reset our memory to the
        # state immediately prior to the generation time of the value.
        if self.owner.lightmem['generation_time'] is not None:
            if gentime < self.owner.lightmem['generation_time']:
                self.owner.lightmem = get_light_state(gentime)
        state, changed = self.owner.lightmem.copy(), []
        state['generation_time'] = gentime
        lights = light_pv["eng_value"]
        for light in luminaire_names.keys():
            on = {'OFF': False, 'ON': True}[lights[light]["measuredState"]]
            if on != self.owner.lightmem[light]:
                changed.append(light)
                state[light] = on
        columns = ("generation_time",) + tuple(luminaire_names.keys())
        # log changes in light state to disk.
        if len(changed) > 0:
            if self.owner.logpath is not None:
                with self.owner.logpath.open("a") as stream:
                    dump = stringify_timedict(state)
                    stream.write(f"{','.join(dump[c] for c in columns)}\n")
        # also prep them for insertion into the database.
        recs = [
            LightRecord(name=light, datetime=gentime, on=state[light])
            for light in changed
        ]
        # if we made records, queue them for transmission to the Station
        if len(recs) > 0:
            node.add_actionable_event(recs, "made_light_records")
        self.owner.lightmem = state

    name = "light_state_processor"


class DBCheck(Actor):
    """
    checks whether a dict constructed from a yamcs parameter contains a
    recordable value that is _not_ a serialized image.

    not currently used.
    """

    def match(self, pdict: dict, **_):
        validate_pdict(pdict)
        if isinstance(pdict["eng_value"], bytes):
            raise NoMatch("eng_value is a bytestring")
        if "imageData" in pdict["eng_value"].keys():
            raise NoMatch("this appears to be image data")
        return True

    def execute(self, node: Node, pdict: dict, **_):
        node.add_actionable_event(node, pdict, "loggable_parameter")

    actortype = "action"
    name = "dbcheck"


class ImageProcessor(Actor):
    """
    Actor that ingests unpacked /ViperGround/Images/ImageData/*
    parameters, writes TIFF files and json labels, and then prepares an
    ImageRecord object for entry into the VIS db. essentially a managed wrapper
    for vipersci.vis.create_image.create().
    """

    def match(self, instruction: Message, **_) -> bool:
        if instruction.action.name != "process_image":
            raise NoMatch("not an image processing instruction")
        if instruction.action.WhichOneof("call") != "localcall":
            raise NoMatch("Not a properly-formatted local call")
        return True

    @reported
    def execute(
        self, node: Node, action: Message, key=None, noid=False, **_
    ) -> ImageRecord:
        # localcall is a serialized mapping created from ParameterData.
        # d is a mapping containing metadata including image header
        # values; im is an ndarray containing the image data.
        d, im = unpack_image_parameter_data(unpack_obj(action.localcall))
        # this converts that to an in-memory ImageRecord object
        return create_image.create(d, im, outdir=self.outdir)

    def _get_outdir(self) -> Path:
        return self._outdir

    def _set_outdir(self, outdir: Path):
        outdir.mkdir(parents=True, exist_ok=True)
        self._outdir = outdir

    _outdir = None
    outdir = property(_get_outdir, _set_outdir)
    interface = ("outdir",)
    actortype = "action"
    name = "image_processor"


class ParameterSensor(Sensor, ABC):
    """
    constructs a yamcs client (optionally a mock one) and uses it to watch
    for new values of specified parameters.
    """

    def __init__(self):
        super().__init__()
        self.cache = deque()
        self._push = push(self.cache)
        self._parameters = []
        self._ctx, self._client, self._processor = None, None, None
        self._initialization_status = "uninitialized"

    def checker(self, _, **__) -> tuple[None, deque]:
        """curried pop-from-cache function"""
        results = popleft(self.cache)
        if self._mock is False:
            results = deque(chain(*[unpack_parameters(r) for r in results]))
        self._count += len(results)
        return None, results

    def _init_subscription(self):
        """try to (re)initialize the subscription."""
        for name in ("_client", "_processor", "parameters"):
            attr = getattr(self, name)
            if (attr is None) or (isinstance(attr, list) and len(attr) == 0):
                self._initialization_status = f"need {name.strip('_')}"
                return
        self._subscription = self._processor.create_parameter_subscription(
            self._parameters, on_data=self._push
        )

    def _init_client(self):
        """try to (re)initialize the client."""
        if self._mock is True:
            if self._ctx is None:
                self._ctx = MockContext()
            self._client = MockYamcsClient(self._ctx)
        elif self.url is None:
            self._initialization_status = "need server url"
            return
        elif self.processor_path is None:
            self._initialization_status = "need processor path"
            return
        else:
            self._client = YamcsClient(self.url)
        self._processor = self._client.get_processor(*self.processor_path)
        self._init_subscription()
        self._initialization_status = "successfully subscribed"

    def _set_parameters(self, parameters: Collection[str]):
        self._parameters = list(parameters)
        self._init_subscription()

    def _get_parameters(self) -> list[str]:
        return self._parameters

    def _set_mock(self, is_mock: bool):
        if not isinstance(is_mock, bool):
            raise DoNotUnderstand("mock must be True or False")
        if is_mock == self._mock:
            return
        self._mock = is_mock
        # (re)initialize client with specified mockness
        self._init_client()

    def _get_mock(self) -> bool:
        return self._mock

    def _get_mock_ctx(self) -> MockContext:
        if self._mock is False:
            raise ValueError("this property may only be used in mock mode")
        return self._ctx

    def _set_mock_ctx(self, ctx: MockContext):
        if self._mock is False:
            raise ValueError("this property may only be used in mock mode")
        self._ctx.kill()
        self._ctx = ctx
        self._init_client()

    def close(self):
        if self._mock is True:
            self._ctx.kill()

    def _get_url(self) -> Optional[str]:
        return self._url

    def _set_url(self, url: str):
        if self._url == url:
            return
        self._url = url
        # we permit setting a url in mock mode, but it doesn't do anything.
        if self.mock is False:
            self._init_client()

    def _get_processor_path(self) -> tuple[str, str]:
        return self._processor_path

    def _set_processor_path(self, path: tuple[str, str]):
        if self._processor_path == path:
            return
        self._processor_path = path
        self._init_client()

    @property
    def initialization_status(self) -> str:
        """
        part of the interface, but cannot be assigned -- simply intended to
        allow flexible initialization order while still giving feedback to the
        Station about errors.
        """
        return self._initialization_status

    @property
    def count(self) -> int:
        """like intialization_status, cannot be assigned."""
        return self._count

    name = "parameter_watch"
    parameters = property(_get_parameters, _set_parameters)
    actions: tuple[Actor]
    mock = property(_get_mock, _set_mock)
    _mock = False
    # note that this is intended to be used only under test via direct
    # assignment within a process, so it is not part of the interface
    mock_context = property(_get_mock_ctx, _set_mock_ctx)
    url = property(_get_url, _set_url)
    _url = None
    processor_path = property(_get_processor_path, _set_processor_path)
    _processor_path = ("viper", "realtime")
    _count = 0
    interface = (
        "count",
        "initialization_status",
        "mock",
        "parameters",
        "processor_path",
        "url",
    )


class ImageSensor(ParameterSensor):
    """
    simple parameter sensor that distinguishes image publications from other
    parameter types.
    """

    actions = (ImageCheck,)
    name = "image_watch"


class LightSensor(ParameterSensor):
    """
    more complex parameter sensor that actually formats LightRecords. this is
    encapsulated in a single Sensor because light state parameter values are
    published in fast cadence (>1/second) whether or not they change, and we
    only care to record them when they change. it is less fragile to only hold
    in-memory state in one place than to have it duplicated between two
    separate delegates or to bother the Station constantly with pointless
    parameter publications; also, handling behavior is much simpler than
    for images.
    """

    def __init__(self):
        super().__init__()
        # initialize from most recent LightRecord per luminaire (if one exists)
        self.lightmem = get_light_state()

    def get_logpath(self) -> Path:
        return self._logpath

    def set_logpath(self, logpath: Path):
        self._logpath = Path(logpath)
        if not self.logpath.exists():
            columns = ("generation_time",) + tuple(luminaire_names.keys())
            with self.logpath.open("w") as stream:
                stream.write(f"{','.join(columns)}\n")

    name = "light_watch"
    actions = (LightStateProcessor,)
    interface = ParameterSensor.interface + ("logpath",)
    logpath = property(get_logpath, set_logpath)
    _logpath = None


class InsertIntoDatabase(Actor):
    """
    take SQLAlchemy DeclarativeBase objects from a report and insert them
    into a database.
    """

    def __init__(self):
        super().__init__()
        self._counts = defaultdict(int)

    def match(self, event: Any, **_) -> bool:
        event = listify(event)
        if not all(isinstance(e, DeclarativeBase) for e in event):
            raise NoMatch("not/not all DeclarativeBases")
        # TODO, maybe: explicitly check against schema, check closed session
        return True

    def execute(self, node, event: Collection[DeclarativeBase], **_):
        event = listify(event)
        with OSession() as session:
            for row in event:
                session.add(row)
            session.commit()
        # do this afterwards because we only want to count successful inserts
        for row in event:
            self._counts[row.__class__.__name__] += 1

    @property
    def counts(self):
        return dict(self._counts)

    interface = ("counts",)
    actortype = ("completion", "info")
    name = "database"


class OrchestratorBase(DeclarativeBase):
    pass


class CreationRecord(OrchestratorBase):
    """table containing a record of db inserts. not currently used."""

    __tablename__ = "creation_record"
    id = mapped_column(Integer, Identity(start=1), primary_key=True)
    instruction_id = mapped_column(
        Integer,
        nullable=False,
        doc="internal orchestrator id for instruction used to create this "
        "product.",
    )
    # TODO: validate oneof
    raw_product = mapped_column(
        ForeignKey(ImageRecord.id),
        nullable=True,
        doc="reference to image record created by this instruction",
    )
    raw_stats = mapped_column(
        ForeignKey(ImageStats.id),
        nullable=True,
        doc="reference to image stats created by this instruction",
    )


# class ArchiveSensor(Sensor):
#     """
#     construct an (optionally mock) yamcs client and use it to
#     query a yamcs archive periodically.
#     """
#
#     def __init__(self):
#         raise NotImplementedError("unfinished, do not use")
#         super().__init__()
#         self._client, self._archive = None, None
#         self._parameter_history = {}
#         self.last_time = None
#
#     def _yamcs_setup(self, reset=False):
#         if (self._archive is not None) and (reset is False):
#             return
#         if (self._mock is True) and (self.server is None):
#             raise ValueError(
#                 "mock_server must be set to use this sensor in mock mode"
#             )
#         elif self.mock is True:
#             self._client = MockYamcsClient(server=self.server)
#             self._archive = self._client.get_archive(self.instance)
#         else:
#             raise NotImplementedError("have to pass the url etc")
#
#     def checker(self, _):
#         # TODO, maybe: this convoluted time tracking thing may not be totally
#         #  necessary, pending clarification
#         self._yamcs_setup()
#         results = []
#         # TODO, maybe: only really need to check this on init, and _could_
#         #  just start from right now, but...
#         if not set(self.parameters).issubset(
#             self.parameter_history.keys()
#         ):
#             raise ValueError(
#                 "Incomplete parameter history, refusing to query from "
#                 "beginning of time"
#             )
#         if (self.offset.seconds != 0) and (self.mock is False):
#             raise ValueError(
#                 "Time offset may not be set unless running in mock mode"
#             )
#         for parameter in self.parameters:
#             new_values = self._archive.list_parameter_values(
#                 parameter,
#                 start=self.parameter_history[parameter]
#             )
#             results += new_values
#             if len(new_values) > 0:
#                 self.last_time[parameter] = max(
#                     v['generation_time'] for v in new_values
#                 )
#         return None,
#
#     def _set_parameters(self, parameters: Collection[str]):
#         self._parameters = list(parameters)
#         self._processor = self._client.get_processor(*self._processor_path)
#         # TODO, maybe: something to remove / reset parameter subscriptions
#         self._subscription = self._processor.create_parameter_subscription(
#             self._parameters, self._push
#         )
#
#     def _get_parameters(self) -> list[str]:
#         return self._parameters
#
#     def _set_mock(self, is_mock: bool):
#         if not isinstance(is_mock, bool):
#             raise DoNotUnderstand("mock must be True or False")
#         if is_mock == self._mock:
#             return
#         self._mock = is_mock
#         # if already initialized, reinitialize with specified mockness
#         if self._archive is not None:
#             self._yamcs_setup(True)
#
#     def _get_mock(self) -> bool:
#         return self._mock
#
#     def _get_mock_server(self) -> Optional[MockServer]:
#         return self._mock_server
#
#     def _set_mock_server(self, server: MockServer):
#         already_had_server = self._mock_server is not None
#         self._mock_server = server
#         if already_had_server:
#             self._yamcs_setup(True)  # otherwise just do it lazily
#
#     def _get_poll(self):
#         return self._poll
#
#     def _set_poll(self, poll: float):
#         self._poll = poll
#
#     def _get_parameter_history(self):
#         return self._parameter_history
#
#     def _set_parameter_history(self, history: Mapping):
#         self._parameter_history = self._parameter_history | history
#
#     def _set_offset(self, offset: dt.timedelta):
#         self._offset = offset
#
#     def _get_offset(self) -> dt.timedelta:
#         return self._offset
#
#     name = "parameter_watch"
#     parameters = property(_get_parameters, _set_parameters)
#     parameter_history = property(
#         _get_parameter_history, _set_parameter_history
#     )
#     actions = (ImageCheck, DBCheck)
#     mock = property(_get_mock, _set_mock)
#     _mock = False
#     _yamcs_url = None
#     poll = property(_get_poll, _set_poll)
#     _poll = 5
#     mock_server = property(_get_mock_server, _set_mock_server)
#     _mock_server = None
#     offset = property(_get_offset, _set_offset)
#     _offset = dt.timedelta(seconds=0)
#     instance = "viper"
#     interface = ("parameters", "mock", "offset", "mock_server")
