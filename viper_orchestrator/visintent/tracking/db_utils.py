from cytoolz import keyfilter
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from func import get_argnames
from viper_orchestrator.db.table_utils import image_request_capturesets
from viper_orchestrator.visintent.tracking.forms import RequestForm


def _create_or_update_entry(
    form, session, pivot, constructor_name=None, extra_attrs=None
):
    try:
        # if this is an existing entry -- as determined by the
        # specified pivot field, which should have been extensively validated
        # at a number of other points -- update it
        if pivot in dir(form):
            ref = getattr(form, pivot)
        else:
            ref = form.cleaned_data[pivot]
        assert ref not in (None, "")
        # capture_id has been cut from ImageRequest so we have to explicitly
        # generate capturesets here. a little ugly but no alternative.
        # TODO, maybe: refactor this function as it is now handling too many
        #  special cases.
        if pivot == "capture_id" and isinstance(form, RequestForm):
            cids = set(map(int, ref.split(",")))
            ref = [
                r
                for r, cs
                in image_request_capturesets().items()
                if cs == cids
            ][0]
            pivot = "id"
        # noinspection PyTypeChecker
        selector = select(form.table_class).where(
            getattr(form.table_class, pivot) == ref
        )
        row = session.scalars(selector).one()
        for k, v in form.cleaned_data.items():
            setattr(row, k, v)
        row.request_time = form.request_time
    except (NoResultFound, AssertionError):
        constructor_kwargs = form.cleaned_data
        if extra_attrs is not None:
            constructor_kwargs |= {
                attr: getattr(form, attr) for attr in extra_attrs
            }
        constructor_kwargs |= {pivot: getattr(form, pivot)}
        # we might have form fields that aren't valid arguments
        # to the (possibly very complicated!) associated DeclarativeBase
        # (table entry) class constructor. Try to automatically filter them.
        valid = set(dir(form.table_class))
        if constructor_name is not None:
            callobj = getattr(form.table_class, constructor_name)
            valid.update(get_argnames(callobj))
        else:
            callobj = form.table_class
        row = callobj(**(keyfilter(lambda k: k in valid, constructor_kwargs)))
        row.request_time = form.request_time
        session.add(row)
    return row
