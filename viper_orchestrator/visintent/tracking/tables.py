"""
like a conventional django models module, but using the SQLAlchemy ORM rather 
than the django ORM for compatibility with vipersci.
"""
from __future__ import annotations

from sqlalchemy import (
    DateTime,
    Identity,
    Integer,
    String,
    select,
)
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm import mapped_column, validates, DeclarativeBase

from viper_orchestrator.db import OSession
from viper_orchestrator.db.session import autosession
from viper_orchestrator.db.table_utils import has_lossless, get_one
from vipersci.vis.db.image_records import ImageRecord


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


class IntentBase(DeclarativeBase):
    pass


class ProtectedListEntry(IntentBase):
    """
    table for entries on the Protected List.

    Note that this table has no direct relationship to ImageRecord. This is
    because an ImageRecord represents an existing product, and existing
    products cannot meaningfully be "protected". a ProtectedListEntry is
    essentially a request for a  _hypothetical_ product, and ceases to be
    operationally useful if and when such a product actually comes into being.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # TODO: sloppy? want to be able to access this before insert, but also
        #  want it in the database
        self.ccu = self.validate_ccu(None, None)

    __tablename__ = "protected_list"
    pl_id = mapped_column(Integer, Identity(start=1), primary_key=True)
    request_pid = mapped_column(
        String, nullable=False, doc="VIS ID used to generate request"
    )
    # image_id and ccu are autopopulated from the VIS ID provided by the user
    image_id = mapped_column(Integer, nullable=False, doc="memory slot number")
    start_time = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="start time of associated image"
    )
    request_time = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="submission/edit time for PL request"
    )
    # 0 or 1,, populated by checking camera against CCU hash
    ccu = mapped_column(Integer, nullable=False, doc="CCU number")
    instrument_name = mapped_column(String, nullable=False, doc="camera name")
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
    def when_fulfilled(self):
        if self._has_lossless is False:
            return None
        if self.has_lossless:
            return self.matching_products[0].start_time
        return None

    @property
    def when_superseded(self):
        if self._superseded is False:
            return None
        with OSession() as session:
            supersessor = session.scalars(self.supselector()).first()
        if supersessor is None:
            return None
        return supersessor.start_time

    def match_selector(self):
        return select(ImageRecord).where(
            ImageRecord.image_id == self.image_id,
            ImageRecord.instrument_name == self.instrument_name,
            ImageRecord.start_time == self.start_time,
        )

    @autosession
    def _populate_matches(self, force=False, session=None):
        if (self._matching_products is not None) and (force is False):
            return
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
    def from_pid(cls, pid, **kwargs):
        pl_attrs = cls.pl_attrs_by_pid(pid)
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
        instance.request_pid = pid
        return instance

    @classmethod
    @autosession
    def search_by_attrs(cls, attrs, session=None):
        # TODO: could be a general-purpose convenience function
        selector = select(cls).where(
            *[getattr(cls, k) == v for k, v in attrs.items()]
        )
        return session.scalars(selector).one()

    @staticmethod
    @autosession
    def pl_attrs_by_pid(pid, session=None):
        try:
            record = get_one(ImageRecord, pid, "_pid", session=session)
        except NoResultFound:
            raise NoResultFound(f"No products with VIS ID '{pid}'.")
        except MultipleResultsFound:
            raise MultipleResultsFound(
                f"Database glitch: multiple products with VIS ID '{pid}'."
            )
        return {
            "instrument_name": record.instrument_name,
            "image_id": record.image_id,
            "start_time": record.start_time,
        }
    #
    # @classmethod
    # def feed(cls, n: int = 10):
    #     events = []
    #     with OSession() as session:
    #         entries = session.scalars(select(cls)).all()
    #     for e in entries:
    #         event = {'entry': e}
    #         if (when := e.when_superseded) is not None:
    #             event['what'], event['when'] = 'superseded', when
    #         elif (when := e.when_fulfilled) is not None:
    #             event['what'], event['when'] = 'fulfilled', when
    #         else:
    #             event['what'], event['when'] = 'added/edited', e.request_time
    #         events.append(event)
    #     events = sorted(events, key=lambda ev: ev['when'], reverse=True)
    #     return events[:n], entries

    _superseded = None
    _has_lossless = None
    _matching_pids = None
    _matching_products = None


