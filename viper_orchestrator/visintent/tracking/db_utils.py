
from functools import wraps
from typing import Collection, Optional, Mapping, Sequence

from cytoolz import keyfilter
from django.forms import Form
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from func import get_argnames
from viper_orchestrator.db import OSession
# from viper_orchestrator.visintent.tracking.forms import (
#     JunctionForm, AppTable, JuncTable,



def autosession(func, manager=OSession):
    @wraps(func)
    def with_session(*args, session=None, **kwargs):
        if session is None:
            with manager as session:
                return func(*args, session=session, **kwargs)
        else:
            return func(*args, session=session, **kwargs)

    return with_session


def _construct_associations(
    # row: AppTable,
    form,
    # table: type[JuncTable],
    kwargspecs: Sequence[Mapping]
):
    associations, removed = [], []
    with OSession() as session:
        rules = form.association_rules[table]
        setattr(form, rules["pivot"][1], getattr(row, rules['pivot'][1]))
        existing = form.get_associations(table, session)
        # leftovers are new relations
    #
    #
    #         associations.append(junc_row)
    # return associations, removed


# TODO: excessively baroque
def _create_or_update_entry(
    form: Form,
    session: Session,
    pivot: str,
    constructor_name: str = None,
    extra_attrs: Optional[Collection[str]] = None,
) -> "AppTable":
    """
    helper function for processing data from bound Forms into DeclarativeBase
    objects
    """
    data = {k: v for k, v in form.cleaned_data.items()}
    if extra_attrs is not None:
        data |= {attr: getattr(form, attr) for attr in extra_attrs}
    try:
        # if this is an existing entry -- as determined by the
        # specified pivot field, which should have been extensively validated
        # at a number of other points -- update it
        if pivot in dir(form):
            ref = getattr(form, pivot)
        else:
            ref = form.cleaned_data[pivot]
        assert ref not in (None, "")
        # TODO: workflow no longer requires capturesets. cut it.
        # capture_id has been cut from ImageRequest so we have to explicitly
        # generate capturesets here. a little ugly but no alternative.
        # TODO, maybe: refactor this function as it is now handling too many
        #  special cases.

        # noinspection PyTypeChecker
        selector = select(form.table_class).where(
            getattr(form.table_class, pivot) == ref
        )
        row = session.scalars(selector).one()
        for k, v in data.items():
            setattr(row, k, v)
    except (NoResultFound, AssertionError):
        data |= {pivot: getattr(form, pivot)}
        # we might have form fields that aren't valid arguments
        # to the (possibly very complicated!) associated DeclarativeBase
        # (table entry) class constructor. Try to automatically filter them.
        valid = set(dir(form.table_class))
        if constructor_name is not None:
            callobj = getattr(form.table_class, constructor_name)
            valid.update(get_argnames(callobj))
        else:
            callobj = form.table_class
        row = callobj(**(keyfilter(lambda attr: attr in valid, data)))
    row.request_time = form.request_time
    associations, removed = [], []
    if isinstance(form, JunctionForm):
        for table, kwargspecs in form.associated.items():
            if len(kwargspecs) == 0:
                continue
            a, r = _construct_associations(row, form, table, kwargspecs)
            associations += a
            removed += r
    session.add_all([row, *associations])
    for r in removed:
        session.delete(r)
    return row
