import datetime as dt
import numpy as np
from PIL import Image
from cytoolz import itemfilter
from dustgoggles.structures import listify
from google.protobuf.message import Message
from imageio.v3 import imread
from io import BytesIO
from pathlib import Path
from sqlalchemy import (
    Integer,
    ForeignKey,
    Identity,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column
from typing import (
    Any,
    MutableSequence,
    Collection,
    Optional,
    Mapping,
)

from db.config import BROWSE_ROOT, DATA_ROOT
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
from hostess.utilities import curry
from vipersci.pds.pid import VISID
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_stats import ImageStats
from vipersci.vis import create_image
from yamcs.tmtc.model import ParameterValue
from viper_orchestrator.db import OSession
from viper_orchestrator.yamcsutils.mock import MockYamcsClient, MockContext


def thumbnail_16bit_tif(
    inpath: Path, outpath: Path, size: tuple[int, int] = (240, 240)
):
    # noinspection PyTypeChecker
    im = np.asarray(Image.open(inpath))
    # PIL's built-in conversion for 16-bit integer images does bad things
    im = Image.fromarray(np.floor(im / 65531 * 255).astype(np.uint8))
    im.thumbnail(size)
    im.save(outpath)


def process_image_instruction(note) -> pro.Action:
    """
    make an Action describing a function call task to be inserted into an
    Instruction.
    """
    instrument = VISID.instrument_name(
        note['data']['eng_value']['imageHeader']['cameraId']
    )
    timestamp = dt.datetime.fromtimestamp(
        note['data']['eng_value']['imageHeader']["lobt"], tz=dt.timezone.utc
    )
    action = make_action(
        name="process_image",
        localcall=pack_obj(note["data"]),
        description={'title': f"{instrument} {timestamp}"}
    )
    return make_instruction("do", action=action)


def thumbnail_instruction(note):
    action = make_function_call_action(
        func="thumbnail_16bit_tif",
        module="viper_orchestrator.station.actors",
        kwargs={
            "inpath": Path(note["content"]),
            "outpath": BROWSE_ROOT / Path(
                note['content']
            ).name.replace(".tif", "_thumb.jpg")
        },
        context="process",
        description={"title": Path(note['content']).name}
    )
    return make_instruction("do", action=action)


def pop(cache: MutableSequence) -> list:
    """pop everything from a sequence and return it in a list"""
    return [cache.pop() for _ in cache]


@curry
def push(cache: MutableSequence, obj: Any):
    """curried push-to-cache function"""
    cache.append(obj)


@curry
def pop_from(
    _, *, cache: Optional[MutableSequence] = None, **__
) -> tuple[None, list]:
    """curried pop-from-cache function"""
    if cache is None:
        return None, []
    return None, pop(cache)


def validate_pdict(pdict: Mapping):
    """
    validates that an object appears to be a dict constructed from a yamcs
    ParameterData object.
    """
    if not isinstance(pdict, Mapping):
        raise NoMatch("this is not a dict")
    if "eng_value" not in pdict.keys():
        raise NoMatch("no eng_value key")


class ImageCheck(Actor):
    """
    checks whether a dict constructed from a yamcs parameter contains a
    serialized image and constructs an actionable event if so.
    """

    def match(self, pdict: dict, **_):
        validate_pdict(pdict)
        if not isinstance(pdict["eng_value"]["imageData"], bytes):
            raise NoMatch("imageData is not a bytestring")
        return True

    def execute(self, node: Node, pdict: dict, **_):
        node.add_actionable_event(
            {
                "data": pdict,
                "parameter": pdict["name"],
                "event_type": "image_published"
            },
            self.owner
        )

    actortype = "action"
    name = "imagecheck"


class DBCheck(Actor):
    """
    checks whether a dict constructed from a yamcs parameter contains a
    recordable value that is _not_ a serialized image.
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


class ParameterSensor(Sensor):
    """
    construct an (optionally mock) yamcs client and use it to
    watch specified parameters.
    """

    def __init__(self, processor_path=("viper", "realtime")):
        super().__init__()
        self._processor_path = processor_path
        self.cache = []
        self._push = push(self.cache)
        self.checker = pop_from(cache=self.cache)
        self._parameters = []
        self._ctx, self._client, self._processor = None, None, None

    def _set_parameters(self, parameters: Collection[str]):
        self._parameters = list(parameters)
        if self._ctx is None:
            if self._mock is True:
                self._ctx = MockContext()
                self._client = MockYamcsClient(self._ctx)
            else:
                raise NotImplementedError("have to pass the url etc")
            self._processor = self._client.get_processor(*self._processor_path)
        # TODO, maybe: something to remove / reset parameter subscriptions
        self._subscription = self._processor.create_parameter_subscription(
            self._parameters, self._push
        )

    def _get_parameters(self) -> list[str]:
        return self._parameters

    def _set_mock(self, is_mock: bool):
        if not isinstance(is_mock, bool):
            raise DoNotUnderstand("mock must be True or False")
        if is_mock == self._mock:
            return
        self._mock = is_mock
        # reinit client with specified mockness
        self.parameters = self._parameters

    def _get_mock(self) -> bool:
        return self._mock

    name = "parameter_watch"
    parameters = property(_get_parameters, _set_parameters)
    actions = (ImageCheck, DBCheck)
    mock = property(_get_mock, _set_mock)
    _mock = False
    interface = ("parameters", "mock")


class ImageProcessor(Actor):
    """
    Actor that ingests unpacked /ViperGround/Images/ImageData/*
    parameters, writes TIFF files and json labels, and then prepares an
    ImageRecord object for entry into the VIS db. essentially a managed wrapper
    for vipersci.vis.create_image.create().
    """

    def __init__(self):
        super().__init__()

    def match(self, instruction: Message, **_) -> bool:
        if instruction.action.name != "process_image":
            raise NoMatch("not an image processing instruction")
        if instruction.action.WhichOneof("call") != "localcall":
            raise NoMatch("Not a properly-formatted local call")
        return True

    @reported
    def execute(self, node: Node, action: Message, key=None, noid=False, **_):
        # localcall is a serialized NestingDict created from ParameterData
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


class InsertIntoDatabase(Actor):
    """
    insert the contents of a report into a database using a SQLAlchemy
    engine/session.
    intended to be used on reports that contain a SQLAlchemy ORM object.
    """

    def match(self, event: Any, **_) -> bool:
        event = listify(event)
        if not all(isinstance(e, DeclarativeBase) for e in event):
            raise NoMatch("not/not all DeclarativeBases")
        # TODO, maybe: explicitly check against schema, check closed session
        return True

    def execute(self, node, event: Collection[DeclarativeBase], **_):
        try:
            event = listify(event)
            with OSession() as session:
                for e in event:
                    # TODO: log db inserts and insert failures
                    session.add(e)
                session.commit()
        # TODO: what exception types am i looking for
        except Exception as ex:
            print(ex)

    # TODO: might want to broaden this.
    actortype = "completion"
    name = "database"


class OrchestratorBase(DeclarativeBase):
    pass


# TODO, maybe: use this?
class CreationRecord(OrchestratorBase):
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


def unpack_image_parameter_data(parameter: ParameterValue | Mapping):
    if not isinstance(parameter, ParameterValue):
        get = parameter.__getitem__
    else:
        get = parameter.__getattribute__
    if len({"imageHeader", "imageData"} & get("eng_value").keys()) != 2:
        raise NotAnImageParameter
    d = (
        {
            "yamcs_name": get("name"),
            "yamcs_generation_time": get("generation_time"),
        }
        | get("eng_value")["imageHeader"]
        | temp_hardcoded_header_values()
    )
    with BytesIO(get("eng_value")["imageData"]) as f:
        im = imread(f)
    if isinstance(parameter, dict):
        # allows us to explicitly manipulate RawProduct constructors
        d |= itemfilter(
            lambda kv: kv[0] not in ("eng_value", "raw_value"), parameter
        )
    return d, im
