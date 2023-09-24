"""
like a conventional django models module, but using the SQLAlchemy ORM rather 
than the django ORM for compatibility with vipersci.
"""
from typing import Sequence, Collection

from sqlalchemy import (
    Boolean,
    DateTime,
    Identity,
    Integer,
    String,
    select,
)
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm import DeclarativeBase, mapped_column, validates

from viper_orchestrator.db import OSession
from vipersci.vis.db.image_records import ImageRecord, ImageType


class AppBase(DeclarativeBase):
    """convenient base for tables managed by the orchestrator"""

    pass


class ImageRequest(AppBase):
    """table for image requests / intents."""

    __tablename__ = "image_requests"
    request_id = mapped_column(Integer, Identity(start=1), primary_key=True)
    title = mapped_column(
        String, nullable=False, doc="short title for request"
    )
    justification = mapped_column(
        String, nullable=False, doc="full description of request intent"
    )
    capture_id = mapped_column(String, unique=True)
    # TODO: determine whether to dynamically or statically update
    status = mapped_column(
        String, nullable=False, default="submitted", doc="request status"
    )
    # note that this cannot be an enum because it may be a set. it is stored
    # as a comma-separated string and must be validated separately.
    ldst = mapped_column(String, nullable=False, doc="LDST matrix elements")
    users = mapped_column(String, nullable=False, doc="requesting user(s)")
    # note: autofilled; this will also track edit time / backfill time.
    request_time = mapped_column(
        DateTime, nullable=False, doc="time of request submission/update"
    )
    # all remaining fields may be null for backfilled requests. they are
    # intended for use in ops.
    target_location = mapped_column(
        String,
        doc="One-line description of what this should be an image "
        "of. May simply be coordinates from MMGIS.",
    )
    rover_location = mapped_column(
        String,
        doc="One-line description of where the rover should be when "
        "the image is taken. May simply be coordinates from MMGIS.",
    )
    rover_orientation = mapped_column(
        String,
        default="any",
        doc="One-line description of desired rover orientation",
    )
    # TODO: how do we handle attached images? are we responsible for file
    #  management?

    imaging_mode = mapped_column(
        String, doc="cameras / imaging mode to be used"
    )

    compression = mapped_column(String, doc="desired compression for image")
    luminaires = mapped_column(
        String, default="default", doc="requested active luminaires"
    )
    caltarget_required = mapped_column(
        Boolean, default=True, doc="acquire caltarget image?"
    )
    aftcam_pair = mapped_column(
        Boolean, default=False, doc="acquire additional aftcam pair?"
    )
    chin_down_navcam_pair = mapped_column(
        Boolean, default=False, doc="acquire chin-down navcam pair?"
    )
    # panorama-only parameters
    need_360 = mapped_column(Boolean, default=False)
    # needed only for non-360 panos
    first_slice_index = mapped_column(Integer)
    last_slice_index = mapped_column(Integer)
    exposure_time = mapped_column(String, default="default")

    # legal values for things.
    # could do some of these as enum columns but very annoying for things that
    # start with numbers, generally more complicated, etc.
    luminaire_generalities = ("default", "none")
    luminaire_tuple_elements = (
        "navlight_left",
        "navlight_right",
        "hazlight_front_left",
        "hazlight_front_right",
        "hazlight_left_side",
        "hazlight_right_side",
        "hazlight_back_left",
        "hazlight_back_right",
    )
    exposures = ("default", "overexposed", "neutral", "underexposed")
    compressions = ("Lossless", "Lossy")
    # TODO: do we want a non-pano image request to be able to handle a series?
    imaging_modes = (
        # empty string for post-hoc intents. TODO: consider autopopulating
        '',
        "navcam_left",
        "navcam_right",
        "navcam_stereo_pair",
        "navcam_panoramic_sequence",
        "aftcam_left",
        "aftcam_right",
        "aftcam_stereo_pair",
        "hazcam_any",
        "hazcam_forward_port",
        "hazcam_forward_starboard",
        "hazcam_aft_port",
        "hazcam_aft_starboard",
    )
    # current status of request.
    # note that this has nothing whatsoever to do with the Protected List.
    # it tracks only image acquisition.
    request_statuses = ("submitted", "rejected", "commanded", "fulfilled")

    @validates("compression")
    def validate_compression(self, _, value: str):
        if value.capitalize() not in self.compressions:
            raise ValueError(f"compression must be in {self.compressions}")
        return value.capitalize()

    @validates("imaging_mode")
    def validate_imaging_mode(self, _, value: str):
        if value not in self.imaging_modes:
            raise ValueError(f"imaging mode must be in {self.imaging_modes}")
        return value

    @validates("luminaires")
    def validate_luminaires(self, _, value: Sequence[str] | str):
        if isinstance(value, str):
            value = value.split(",")
        if len(value) == 0:
            raise ValueError(
                "at least 'default' must be specified for luminaires"
            )
        if len(value) == 1:
            legal = self.luminaire_tuple_elements + self.luminaire_generalities
            if value[0] not in legal:
                raise ValueError(f"single luminaire entry must be in {legal}")
        if len(value) == 2:
            if not all(v in self.luminaire_tuple_elements for v in value):
                raise ValueError(
                    f"2-element requests must be selected from:"
                    f"{self.luminaire_tuple_elements}"
                )
        if len(value) > 2:
            raise ValueError("max 2 luminaires per request")
        return ",".join(value)

    @validates("request_status")
    def validate_request_status(self, _, value: str):
        if value not in self.request_statuses:
            raise ValueError(
                f"request status must be in {self.request_statuses}"
            )
        return value

    @validates("capture_id")
    def validate_capture_id(self, _, value: str | None):
        if value is None:
            return
        if (isinstance(value, str)) and (value.lower() == "none"):
            return
        try:
            ids = set(map(int, str(value).replace(" ", "").split(",")))
        except (ValueError, AttributeError, TypeError):
            raise ValueError(
                "capture id must be a base-10 integer or a comma-separated "
                "list of base-10 integers"
            )
        for request_id, cs in self.capturesets().items():
            if request_id == self.request_id:
                continue
            if not ids.isdisjoint(cs):
                raise ValueError(
                    f"Capture ID(s) {ids.intersection(cs)} have already "
                    f"been associated with another image request."
                )
        return ",".join(map(str, ids))

    # this is a little inefficient but I don't really want to make a
    # table for captures to permit a formal one-to-many relationship
    @classmethod
    def capturesets(cls):
        capturemap = {}
        with OSession() as session:
            requests = session.execute(select(cls.capture_id, cls.request_id))
            for capture_id, pk in requests:
                if capture_id is None:
                    continue
                capturemap[pk] = set(
                    map(int, capture_id.replace(" ", "").split(","))
                )
        return capturemap


CCU_HASH = {
    "NavCam Left": 0,
    "NavCam Right": 0,
    "HazCam Aft Port": 0,
    "HazCam Aft Starboard": 0,
    "AftCam Left": 1,
    "AftCam Right": 1,
    "HazCam Forward Port": 1,
    "HazCam Forward Starboard": 1,
}

CCU_REVERSE_HASH = {
    0: (
        "NavCam Left",
        "NavCam Right",
        "HazCam Aft Port",
        "HazCam Aft Starboard",
    ),
    1: (
        "AftCam Left",
        "AftCam Right",
        "HazCam Forward Port",
        "HazCam Forward Starboard",
    ),
}


class ProtectedListEntry(AppBase):
    """table for entries on the Protected List."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # TODO: sloppy? want to be able to access this before insert, but also
        #  want it in the database
        self.ccu = self.validate_ccu(None, None)

    __tablename__ = "protected_list"
    pl_id = mapped_column(Integer, Identity(start=1), primary_key=True)
    # image_id and ccu are autopopulated from the VIS ID provided by the user
    image_id = mapped_column(Integer, nullable=False, doc="memory slot number")
    start_time = mapped_column(
        DateTime, nullable=False, doc="start time of associated image"
    )
    request_time = mapped_column(
        DateTime, nullable=False, doc="submission/edit time for PL request"
    )
    # 0 or 1,, populated by checking camera against CCU hash
    ccu = mapped_column(Integer, nullable=False, doc="CCU number")
    instrument_name = mapped_column(String, nullable=False, doc="camera name")
    # temporarily removing this in lieu of simple 'Lossless' and 'Lossy'
    # target_compression = mapped_column(
    #     Integer,
    #     nullable=True,
    #     doc="desired compression ratio for re-downlinked image",
    # )
    rationale = mapped_column(
        String, nullable=False, doc="rationale for entry on protected list"
    )

    @validates("ccu")
    def validate_ccu(self, _, __):
        try:
            return CCU_HASH[self.instrument_name]
        except KeyError:
            raise ValueError(f"unknown instrument {self.instrument_name}")

    def supselector(self):
        return select(ImageRecord).where(
            ImageRecord.image_id == self.image_id,
            ImageRecord.instrument_name.in_(CCU_REVERSE_HASH[self.ccu]),
            ImageRecord.start_time > self.start_time,
            )

    @property
    def superseded(self):
        # autocaches. if this is a problem, we can change it.
        if self._superseded is not None:
            return self._superseded

        with OSession() as session:
            try:
                assert session.scalars(self.supselector()).first() is not None
                self._superseded = True
            except AssertionError:
                self._superseded = False
        return self._superseded

    @property
    def when_superseded(self):
        if self._superseded is False:
            return None
        with OSession() as session:
            supersessor = session.scalars(self.supselector()).first()
        if supersessor is None:
            return None
        return supersessor.start_time

    # TODO: this should actually use the downlink time. can we get that?
    @property
    def when_fulfilled(self):
        if self._has_lossless is False:
            return None
        if self.has_lossless:
            return self.matching_products[0].start_time
        return None

    def match_selector(self):
        return select(ImageRecord).where(
            ImageRecord.image_id == self.image_id,
            ImageRecord.instrument_name == self.instrument_name,
            ImageRecord.start_time == self.start_time,
        )

    def _populate_matches(self, force=False):
        if (self._matching_products is not None) and (force is False):
            return
        with OSession() as session:
            products = session.scalars(self.match_selector()).all()
            self._has_lossless = has_lossless(products)
            self._matching_pids = tuple(p.product_id for p in products)
            self._matching_products = products

    @property
    def matching_pids(self):
        self._populate_matches()
        return self._matching_pids

    @property
    def has_lossless(self):
        self._populate_matches()
        return self._has_lossless

    @property
    def matching_products(self):
        self._populate_matches()
        return self._matching_products

    @classmethod
    def from_pid(cls, product_id, **kwargs):
        pl_attrs = cls.pl_attrs_by_pid(product_id)
        try:
            instance = cls.search_by_attrs(pl_attrs)
        except (ValueError, NoResultFound):
            instance = cls(**pl_attrs, rationale="")
        # just a convenience to allow us to pass pl_id around without
        # interfering with sqlalchemy's autoincrementing pk behavior
        if kwargs.get("pl_id") == "":
            kwargs.pop("pl_id")
        for k, v in kwargs.items():
            setattr(instance, k, v)
        return instance

    @classmethod
    def search_by_pid(cls, pid):
        return cls.search_by_attrs(cls.pl_attrs_by_pid(pid))

    @classmethod
    def search_by_attrs(cls, attrs):
        # TODO: could be a general-purpose convenience function
        with OSession() as session:
            selector = select(cls).where(
                *[getattr(cls, k) == v for k, v in attrs.items()]
            )
            return session.scalars(selector).one()

    @staticmethod
    def pl_attrs_by_pid(pid):
        with OSession() as session:
            raw_selector = select(ImageRecord).where(
                ImageRecord.product_id == pid
            )
            try:
                match = session.scalars(raw_selector).one()
            except NoResultFound:
                raise ValueError("No VIS products with this PID.")
            except MultipleResultsFound:
                raise ValueError(
                    "Database glitch: multiple VIS products with this PID."
                )
            return {
                "instrument_name": match.instrument_name,
                "image_id": match.image_id,
                "start_time": match.start_time,
            }

    @classmethod
    def feed(cls, n: int = 10):
        events = []
        with OSession() as session:
            entries = session.scalars(select(cls)).all()
        for e in entries:
            event = {'entry': e}
            if (when := e.when_superseded) is not None:
                event['what'], event['when'] = 'superseded', when
            elif (when := e.when_fulfilled) is not None:
                event['what'], event['when'] = 'fulfilled', when
            else:
                event['what'], event['when'] = 'added/edited', e.request_time
            events.append(event)
        events = sorted(events, key=lambda ev: ev['when'], reverse=True)
        return events[:n], entries

    _superseded = None
    _has_lossless = None
    _matching_pids = None
    _matching_products = None


def has_lossless(products):
    return any(
        ImageType(p.output_image_mask).name.startswith("LOSSLESS")
        for p in products
    )


def capture_ids_to_product_ids(
    cids: int | str | Collection[int | str]
) -> set[str]:
    if isinstance(cids, str):
        cids = map(int, cids.split(","))
    elif isinstance(cids, int):
        cids = {cids}
    else:
        cids = map(int, cids)
    pids = []
    with OSession() as session:
        for cid in cids:
            # noinspection PyTypeChecker
            selector = select(ImageRecord).where(ImageRecord.capture_id == cid)
            pids += [p.product_id for p in session.scalars(selector).all()]
    return set(pids)
