from typing import Collection, Optional

from cytoolz import keyfilter
from django.forms import Form
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound, InvalidRequestError

from func import get_argnames
from sqlalchemy.orm import Session, DeclarativeBase

from viper_orchestrator.db import OSession
from viper_orchestrator.db.table_utils import image_request_capturesets
from viper_orchestrator.visintent.tracking.forms import RequestForm


def _construct_associations(association_data, association_rules, row):
    associations = []
    for k, v in association_data.items():
        rules = association_rules[k]
        junc, pivot = rules['junc'], rules['pivot']
        for assoc in v:
            try:
                with OSession() as session:
                    selector = select(junc).where(
                        getattr(junc, pivot[0]) == getattr(row, pivot[1])
                    )
                    association = session.scalars(selector).one()
            except (AssertionError, InvalidRequestError):
                association = rules['junc']()
            for attr, val in assoc.items():
                setattr(association, attr, val)
            setattr(association, rules['self_attr'], row)
            associations.append(association)
    return associations


def _separate_associations(form):
    row_data, association_data = {}, {}
    for k, v in form.cleaned_data.items():
        if (
            hasattr(form, "associated_tables")
            and form.associated_tables.get(k) is not None
        ):
            association_data[k] = v
        else:
            row_data[k] = v
    return row_data, association_data


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
    data, association_data = _separate_associations(form)
    if extra_attrs is not None:
        data |= {
            attr: getattr(form, attr) for attr in extra_attrs
        }
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
    if len(association_data) > 0:
        associations = _construct_associations(
            association_data, form.associated_tables, row
        )
    else:
        associations = []
    session.add_all([row, *associations])
    return row, associations