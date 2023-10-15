import datetime as dt
from pathlib import Path
import random
from string import ascii_letters
from typing import Optional, Mapping, Collection, Literal

from django.forms import (
    ChoiceField,
    MultipleChoiceField,
    BooleanField,
    IntegerField,
    CharField,
    DateTimeField,
    Form,
)
from hostess.utilities import curry
from sqlalchemy import select

from viper_orchestrator.config import (
    PARAMETERS,
    MOCK_EVENT_PARQUET,
    MOCK_BLOBS_FOLDER,
)
from vipersci.vis.db.image_records import ImageRecord

from viper_orchestrator.db import OSession
from viper_orchestrator.yamcsutils.mock import MockServer, MockContext
from viper_orchestrator.visintent.tracking.forms import PLSubmission
from viper_orchestrator.visintent.tracking.db_utils import (
    _create_or_update_entry,
)

# where do our mock events live?
MOCK_ROOT = Path("../mock_data/mock_events_b6s3_all_cameras_icer")
sample = curry(random.sample)  # shorthand utility function


class FakeWSGIRequest:
    """mock django WSGIRequest"""

    def __init__(self, get_values: Optional[Mapping]):
        if get_values is not None:
            self.GET = get_values


def randomize_form(form: Form, skipfields: Collection[str] = ()):
    """
    fill an unbound django Form with random data, then bind and validate it.
    likely to fail on forms with complex validation rules.
    """
    for name, field in form.fields.items():
        if name in skipfields:
            if name in form.data.keys():
                continue
            form.data[name] = field.initial
        elif isinstance(field, (ChoiceField, MultipleChoiceField)):
            form.data.setlist(
                name,
                random.choices(
                    [c[0] for c in field.choices], k=random.randint(1, 2)
                )
            )
        elif isinstance(field, BooleanField):
            form.data[name] = random.choice((True, False))
        elif isinstance(field, IntegerField):
            form.data[name] = random.randint(1, 8)
        elif isinstance(field, CharField):
            form.data[name] = "".join(random.choices(ascii_letters, k=8))
        elif isinstance(field, DateTimeField):
            form.data[name] = dt.datetime.now()
    form.is_bound = True
    assert form.is_valid()


def image_records_by_compression() -> dict[
    Literal["lossy", "lossless"], list[ImageRecord]
]:
    """return a dict distinguishing lossy from lossless ImageRecords."""
    with OSession() as session:
        products = session.scalars(select(ImageRecord)).all()
    compdict = {"lossy": [], "lossless": []}
    for product in products:
        if product.product_id[-1] in ("z", "a"):
            compdict["lossless"].append(product)
        else:
            compdict["lossy"].append(product)
    return compdict


def make_mock_server(ctx: Optional[MockContext] = None) -> MockServer:
    """
    create a mock yamcs server backed by a parquet file and a directory of
    binary blobs
    """
    server = MockServer(
        events=MOCK_EVENT_PARQUET,
        blobs_folder=MOCK_BLOBS_FOLDER,
        mode="sequential",
    )
    server.parameters = list(PARAMETERS)
    # optionally, connect this server to a MockContext used by one or more
    # ParameterSensors -- this is a mock for connecting to the yamcs server's
    # pub socket.
    if ctx is not None:
        server.ctx = ctx
    return server


def make_random_pl_submission(pid: int):
    plform = PLSubmission(product_id=pid)
    randomize_form(plform)
    with OSession() as session:
        _create_or_update_entry(
            plform, session, "pl_id", "from_pid", ("product_id",)
        )
        session.commit()
