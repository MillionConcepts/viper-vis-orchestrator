from typing import Collection, Optional, Union, Mapping, Any, MutableMapping, \
    Sequence

from cytoolz import keyfilter
from django.forms import Form
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound, InvalidRequestError

from func import get_argnames
from sqlalchemy.orm import Session, DeclarativeBase

from viper_orchestrator.db import OSession
from viper_orchestrator.db.table_utils import image_request_capturesets
from viper_orchestrator.visintent.tracking.forms import (
    RequestForm,
    JunctionForm, AssociationRule, AppTable, JuncTable,
)
from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest


def _construct_associations(
    row: AppTable,
    form,
    table: type[JuncTable],
    kwargspecs: Sequence[Mapping]
):
    associations, removed = [], []
    with OSession() as session:
        rules = form.association_rules[table]
        setattr(form, rules["pivot"][1], getattr(row, rules['pivot'][1]))
        existing = form.get_associations(table, session)
        relations = {i: r for i, r in enumerate(kwargspecs)}
        for junc_row in existing:
            matches = [
                k
                for k, v in relations.items()
                if v == getattr(junc_row, rules["junc_pivot"])
            ]
            if len(matches) == 0:
                removed.append(junc_row)
            elif len(matches) == 1:
                raise InvalidRequestError(
                    "Only one matching row is expected here; table "
                    "contents appear invalid"
                )
            else:
                match = relations.pop(matches[0])
                for attr, val in match.items():
                    setattr(junc_row, attr, val)
                associations.append(junc_row)
        # leftovers are new relations
        for v in relations.values():
            junc_row = table()
            for attr, val in v.items():
                setattr(junc_row, attr, val)
            # this should already be set on existing junc table rows
            setattr(junc_row, rules["self_attr"], row)
            associations.append(junc_row)
    return associations, removed


# TODO: excessively baroque
def _create_or_update_entry(
    form: Form,
    session: Session,
    pivot: str,
    constructor_name: str = None,
    extra_attrs: Optional[Collection[str]] = None,
) -> tuple[DeclarativeBase, list[DeclarativeBase]]:
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
        if pivot == "capture_id" and isinstance(form, RequestForm):
            cids = set(map(int, ref.split(",")))
            ref = [
                r
                for r, cs in image_request_capturesets().items()
                if cs == cids
            ][0]
            pivot = "id"
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
