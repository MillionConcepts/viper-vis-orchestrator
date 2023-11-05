"""django view functions and helpers."""
import json
import shutil
from collections import defaultdict
from typing import Optional

from cytoolz import groupby, valmap
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm import Session

# noinspection PyUnresolvedReferences
from viper_orchestrator.config import DATA_ROOT, PRODUCT_ROOT
from viper_orchestrator.db.session import autosession
from viper_orchestrator.db.table_utils import (
    get_one, iterquery, )
from viper_orchestrator.exceptions import (
    AlreadyDeletedError,
    AlreadyLosslessError,
    BadURLError,
)
from viper_orchestrator.orchtypes import DjangoResponseType
from viper_orchestrator.visintent.tracking.forms import (
    AssignRecordForm,
    PLSubmission,
    RequestForm,
    VerificationForm, EvaluationForm, )
from viper_orchestrator.visintent.tracking.forms import (
    request_supplementary_path,
)
from viper_orchestrator.visintent.tracking.tables import (
    CCU_HASH,
    ProtectedListEntry,
)
from viper_orchestrator.visintent.tracking.vis_db_structures import \
    req_info_record, ldst_status_dict, review_info_dict, rec_file_links, \
    protected_list_record, image_rec_brief
from viper_orchestrator.visintent.visintent.settings import (
    BROWSE_URL,
    DATA_URL,
)
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest, Status


@never_cache
@autosession
def imageview(
    request: WSGIRequest,
    session=None,
    assign_record_form=None,
    verification_form=None,
    pid=None,
    rec_id=None,
    **_regex_kwargs,
) -> HttpResponse:
    try:
        if rec_id is not None:
            record = get_one(ImageRecord, int(rec_id), session=session)
        else:
            if pid is None:
                pid = request.path.strip("/")
            record = get_one(ImageRecord, pid, "_pid", session=session)
    except NoResultFound:
        suffix = f"id {rec_id}" if rec_id is not None else f"product id {pid}"
        return HttpResponse(
            f"No image in the database has {suffix}.", status=404,
        )
    label_path_stub = record.file_path.replace(".tif", ".json")
    with (DATA_ROOT / label_path_stub).open() as stream:
        metadata = json.load(stream)
    metadata["verified"] = record.verified
    metadata['verification_notes'] = record.verification_notes
    metadata['id'] = record.id
    if record.image_request is None:
        ecode, request_url, req_id = "no request", None, ""
    else:
        req_id = record.image_request.id
        request_url = f"imagerequest?req_id={req_id}&editing=True"
        ecode = RequestForm(
            image_request=get_one(ImageRequest, req_id, session=session)
        ).ecode
        # these will usually be None in the on-disk labels
        metadata["image_request_id"] = req_id
    if assign_record_form is None:
        assign_record_form = AssignRecordForm(rec_id=record.id, req_id=req_id)
    if (reqerr := assign_record_form.errors.get('req_id')) is not None:
        reqerr = reqerr[0]
    else:
        reqerr = None
    if verification_form is None:
        verification_form = VerificationForm(image_record=record)
    return render(
        request,
        "image_view.html",
        {
            "assign_record_form": assign_record_form,
            "browse_url": (
                BROWSE_URL + record.file_path.replace(".tif", "_browse.jpg")
            ),
            "ecode": ecode,
            "image_url": DATA_URL + record.file_path,
            "label_url": DATA_URL + label_path_stub,
            "metadata": metadata,
            "pid": record._pid,
            "rec_id": record.id,
            "pagetitle": record._pid,
            "request_url": request_url,
            "verification_form": verification_form,
            "reqerr": reqerr
        },
    )


@never_cache
@autosession
def assign_record(request: WSGIRequest, session=None) -> DjangoResponseType:
    """associate an ImageRecord with an ImageRequest"""
    from viper_orchestrator.visintent.tracking.forms import AssignRecordForm

    form = AssignRecordForm(request.POST)
    if not form.is_valid():
        return imageview(
            request, pid=request.POST["pid"], assign_record_form=form
        )
    form.commit(session=session)
    return imageview(
        request, req_id=request.GET.get("rec_id"), pid=request.POST["pid"]
    )


@never_cache
def imagerequest(
    request: WSGIRequest,
    request_form: Optional[RequestForm] = None,
    evaluation_form: Optional[EvaluationForm] = None,
    redirect_from_success: bool = False
) -> HttpResponse:
    """render image request form page"""
    if request_form is None:
        request_form = RequestForm.from_wsgirequest(request, submitted=False)
    # form not None implies that we are kicking it back with errors
    editing = request.GET.get("editing", True)
    template = "image_request.html" if editing is True else "request_view.html"
    bound = {f.name: f.value for f in tuple(request_form)}
    # these variables are used only for non-editing display
    showpano = bound["camera_request"]() == "navcam_panorama"
    showslice = (bound["need_360"]() is True) and showpano
    if request_form.req_id is None and editing is False:
        return HttpResponse(
            "cannot generate view for nonexistent image request",
            status=400
        )
    filename, file_url = request_form.filepaths()
    context = {
        "form": request_form,
        "showpano": showpano,
        "showslice": showslice,
        "filename": filename,
        "file_url": file_url,
        "pagetitle": "Image Request",
        "verification_json": json.dumps(request_form.verification_status),
        "request_error_json": request_form.errors.as_json(),
        "redirect_from_success": redirect_from_success,
        "live_form_state": request.POST.get("live_form_state", "{}")
    }
    if request_form.image_request is not None:
        context["req_info_json"] = json.dumps(
            req_info_record(request_form.image_request)[0]
        )
    else:
        context["req_info_json"] = "{}"
    if evaluation_form is not None:
        # if we have an evaluation form, assume the user marked the hypothesis
        # as critical even if it hasn't been saved to the database yet (likely
        # because of evaluation form errors)
        request_form.eval_info[evaluation_form.hyp]['relevant'] = True
        request_form.eval_info[evaluation_form.hyp]['critical'] = True
        # noinspection PyTypedDict
        context['eval_ui_status'] = json.dumps({
            'hyp': evaluation_form.hyp,
            'errors': evaluation_form.errors.as_json(),
            'success': len(evaluation_form.errors) == 0
        })
        context['redirect_from_evaluation'] = True
    else:
        context['eval_ui_status'] = "{}"
        context['redirect_from_evaluation'] = False
    context["eval_json"] = json.dumps(request_form.eval_info)
    try:
        return render(request, template, context)
    except BadURLError as bue:
        return HttpResponse(str(bue), status=400)


@never_cache
@autosession
def submitverification(
    request: WSGIRequest, session: Optional[Session] = None
) -> DjangoResponseType:
    image_record = get_one(ImageRecord, int(request.POST['rec_id']))
    form = VerificationForm(
        request.POST, session=session, image_record=image_record
    )
    if not form.is_valid():
        return imageview(
            request, rec_id=request.POST['rec_id'], verification_form=form
        )
    form.commit(session=session)
    return imageview(request, rec_id=request.POST['rec_id'])


def submitevaluation(request: WSGIRequest) -> DjangoResponseType:
    form = EvaluationForm.from_wsgirequest(request)
    if form.is_valid() is False:
        return imagerequest(request, evaluation_form=form)
    form.commit()
    return imagerequest(request, evaluation_form=form)


@never_cache
def submitrequest(request: WSGIRequest) -> DjangoResponseType:
    """
    handle request submission and redirect to errors or success notification
    as appropriate
    """
    form = RequestForm.from_wsgirequest(request, submitted=True)
    if form.is_valid() is False:
        return imagerequest(request)
    try:
        form.commit()
    except (ValueError, TypeError) as err:
        form.add_error(None, str(err))
        return imagerequest(request_form=form)
    if (fileobj := request.FILES.get("supplementary_file")) is not None:
        filepath = request_supplementary_path(form.req_id, fileobj.name)
        shutil.rmtree(filepath.parent, ignore_errors=True)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "wb") as stream:
            stream.write(fileobj.read())
    return requestlist(request, redirect_from_success=True)


@autosession
@never_cache
def requestlist(request, session=None, redirect_from_success=False):
    """prep and render list of all existing requests"""
    rows = session.scalars(select(ImageRequest)).all()
    rows.sort(key=lambda r: r.request_time, reverse=True)
    records = [req_info_record(row)[0] for row in rows]
    # TODO: paginate, preferably configurably
    return render(
        request,
        "request_list.html",
        {
            "request_json": json.dumps(records),
            "statuses": ["all", *[s.name for s in Status]],
            'redirect_from_success': redirect_from_success
        },
    )


@never_cache
@autosession
def ldst(
    request: WSGIRequest, session: Optional[Session]
) -> DjangoResponseType:
    """render LDST status page"""
    return render(
        request,
        "ldst_status.html",
        context=valmap(json.dumps, ldst_status_dict(session))
    )


# TODO, maybe: if there are performance issues with this as db size increases,
#  selectively populate via Fetch API
@never_cache
@autosession
def review(
    request: WSGIRequest, session: Optional[Session]
) -> DjangoResponseType:
    return render(
        request,
        "review.html",
        context=valmap(json.dumps, review_info_dict(session))
    )


@never_cache
def plrequest(request):
    """render pl request form page"""
    pid, pl_id = (request.GET.get(k) for k in ("pid", "pl_id"))
    if (pid is None) and (pl_id is None):
        return render(request, "pl_landing.html")
    if pid is not None:
        pid = pid.strip()
    try:
        form = PLSubmission(pid=pid, pl_id=pl_id)
    except AlreadyLosslessError:
        return HttpResponse(
            "Fortunately, this image has already been downlinked with "
            "lossless compression. No need to create request to protect it."
        )
    except AlreadyDeletedError:
        return HttpResponse(
            "Unfortunately, this image no longer exists in the "
            "CCU. Cannot create request to protect it."
        )
    except (NoResultFound, MultipleResultsFound) as nrf:
        return HttpResponse(str(nrf))
    return render(
        request,
        "add_to_pl.html",
        {"form": form, "pagetitle": "Protected List Request"},
    )


def get_last_image_ids(session):
    last_image_ids = {0: None, 1: None}
    for recs in iterquery(
            select(ImageRecord), ImageRecord.start_time, session=session
    ):
        by_ccu = groupby(lambda r: CCU_HASH[r.instrument_name], recs)
        for ccu in (0, 1):
            if last_image_ids[ccu] is not None:
                continue
            if len(by_ccu[ccu]) > 0:
                last_image_ids[ccu] = by_ccu[ccu][0].image_id
        if all(v is not None for v in last_image_ids.values()):
            break
    return last_image_ids


@never_cache
@autosession
def pllist(request, redirect_from_success=False, session=None):
    """
    prep and render list of all existing protected list entries, along with
    most recent downlinked image ID (memory location) for each CCU
    """

    last_ids = get_last_image_ids(session)
    rows = session.scalars(select(ProtectedListEntry)).all()
    rows.sort(key=lambda r: r.request_time, reverse=True)
    records = [protected_list_record(row) for row in rows]
    return render(
        request,
        "pl_display.html",
        {
            "pl_json": json.dumps(records),
            "write_head": {'zero': last_ids[0], 'one': last_ids[1]},
            "pagetitle": "Protected List Display",
            "redirect_from_success": redirect_from_success
        },
    )


@autosession
def submitplrequest(request, session=None):
    """
    handle pl request submission and redirect to error or success notification
    as appropriate
    """
    pid, pl_id = (request.GET.get(k) for k in ("pid", "pl_id"))
    if pid is not None:
        pid = pid.strip()
    form = PLSubmission(request.GET, pid=pid, pl_id=pl_id)
    if form.is_valid() is False:
        return render(request, "add_to_pl.html", {"form": form})
    try:
        form.commit(session=session, constructor_method="from_pid")
    except (ValueError, NoResultFound) as err:
        form.add_error(None, str(err))
        return render(request, "add_to_pl.html", {"form": form})
    return pllist(request, redirect_from_success=True)


@never_cache
@autosession
def imagelist(request, session=None):
    """prep and render list of all existing images"""
    rows = session.scalars(select(ImageRecord)).all()
    # noinspection PyUnresolvedReferences
    rows.sort(key=lambda r: r.start_time, reverse=True)
    records = defaultdict(list)
    for row in rows:
        record = image_rec_brief(row)
        records["all"].append(record)
        records[record["instrument"].split(" ")[0]].append(record)
    return render(
        request,
        "image_list.html",
        {
            "record_json": json.dumps(records),
            "pagetitle": "Image List",
            "instruments": records.keys()
        },
    )


def pages(request):
    return render(request, "pages.html")
