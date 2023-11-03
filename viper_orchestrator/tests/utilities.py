import datetime as dt
import shutil
from pathlib import Path
import random
from string import ascii_letters
from typing import Optional, Mapping, Collection, Literal, Union

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
    DATA_ROOT,
    BROWSE_ROOT
)
from viper_orchestrator.db.session import autosession
from vipersci.vis.db.image_records import ImageRecord

from viper_orchestrator.db import OSession
from viper_orchestrator.yamcsutils.mock import MockServer, MockContext
from viper_orchestrator.visintent.tracking.forms import PLSubmission, \
    RequestForm

# from viper_orchestrator.visintent.tracking.db_utils import (
#     _create_or_update_entry,
# )

# where do our mock events live?
MOCK_ROOT = Path("../mock_data/mock_events_b6s3_all_cameras_icer")
sample = curry(random.sample)  # shorthand utility function


class FakeWSGIRequest:
    """mock django WSGIRequest"""

    def __init__(
        self,
        get_values: Optional[Mapping] = None,
        post_values: Optional[Mapping] = None
    ):
        self.GET = get_values if get_values is not None else {}
        self.POST = post_values if post_values is not None else {}
        self.META = {}


def randomize_request_form(form: RequestForm):
    hyps = random.choices(tuple(form.ldst_hypotheses), k=random.randint(1, 3))
    critical = [True if random.random() > 0.5 else False for _ in hyps]
    form.ldst_hypotheses |= {
        h: {'relevant': True, 'critical': c} for h, c in zip(hyps, critical)
    }
    form.data['luminaires'] = random.choice(
        form.fields['luminaires'].choices
    )[0]
    return form


def randomize_form(form: Form, skipfields: Collection[str] = ()):
    """
    fill an unbound django Form with random data, then bind and validate it.
    needs special cases for forms with complex validation rules.
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
    if isinstance(form, RequestForm):
        form = randomize_request_form(form)
    form.is_bound = True
    assert form.is_valid()


@autosession
def image_records_by_compression(session=None) -> dict[
    Literal["lossy", "lossless"], list[ImageRecord]
]:
    """return a dict distinguishing lossy from lossless ImageRecords."""
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


def make_random_pl_submission(pid: int, commit=True):
    plform = PLSubmission(pid=pid)
    randomize_form(plform)
    if commit is True:
        plform.commit(constructor_method="from_pid")


def copy_imagerecord(
    source: ImageRecord,
    offset: Optional[Union[dt.timedelta, int]] = None,
    copy_files: bool = False,
    **extra_kwargs
):
    if offset is None:
        offset = dt.timedelta(
            hours=random.randint(1, 110), minutes=random.randint(1, 60)
        )
    elif isinstance(offset, int):
        offset = dt.timedelta(seconds=offset)
    times = {
        t: getattr(source, t) + offset for
        t in ('start_time', 'yamcs_generation_time')
    }
    # TODO: this might not be saved appropriately in ImageRecord?
    times['yamcs_reception_time'] = (
        times['yamcs_generation_time'] + dt.timedelta(minutes=1)
    )
    times['lobt'] = int(times['start_time'].timestamp())
    product_dict = source.asdict() | times
    del product_dict['product_id']
    del product_dict['id']
    new = ImageRecord(**(product_dict | extra_kwargs))
    if copy_files is True:
        for d in (DATA_ROOT, BROWSE_ROOT):
            for m in [f for f in d.iterdir() if source._pid in f.name]:
                shutil.copy(m, d / m.name.replace(source._pid, new._pid))
        new.file_path = source.file_path.replace(source._pid, new._pid)
    return new

