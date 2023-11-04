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
from dustgoggles.structures import NestingDict
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm import Session

# noinspection PyUnresolvedReferences
from viper_orchestrator.config import DATA_ROOT, PRODUCT_ROOT
from viper_orchestrator.db.session import autosession
from viper_orchestrator.db.table_utils import (
    image_request_capturesets,
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
from viper_orchestrator.visintent.visintent.settings import (
    BROWSE_URL,
    DATA_URL,
)
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest, Status
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST


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
        record: ImageRecord
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
    if record.image_request is None:
        evaluation, request_url, req_id = "no request", None, ""
        metadata["verified"] = record.verified
        metadata['verification_notes'] = record.verification_notes
        metadata['id'] = record.id
    else:
        req_id = record.image_request.id
        request_url = f"imagerequest?req_id={req_id}&editing=True"
        evaluation = "not"
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
            "evaluation": evaluation,
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
    return imageview(request, pid=request.POST["pid"])


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
            request_info_record(request_form.image_request)[0]
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
        context['eval_ui_status'] = {
            'hyp': evaluation_form.hyp,
            'errors': evaluation_form.errors.as_json(),
        }
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
    return imagerequest(request, redirect_from_success=True)


@autosession
@never_cache
def requestlist(request, session=None):
    """prep and render list of all existing requests"""
    rows = session.scalars(select(ImageRequest)).all()
    rows.sort(key=lambda r: r.request_time, reverse=True)
    records = []
    for row in rows:
        form = RequestForm(image_request=row)
        record = {
            "title": row.title,
            "request_time": row.request_time.isoformat()[:19] + "Z",
            "view_url": (
                f"/imagerequest?req_id={row.id}&editing=false"
            ),
            "justification": row.justification,
            "req_id": row.id,
            "pagetitle": "Image Request List",
            "status": row.status.name,
            "n_images": len(row.image_records),
            "verification": form.verification_code,
            "evaluation": form.eval_code
        }
        records.append(record)
    # TODO: paginate, preferably configurably
    return render(
        request,
        "request_list.html",
        {"records": records, "statuses": [s.name for s in Status]},
    )


def _get_hyps(hyp, session):
    # noinspection PyTypeChecker
    return session.scalars(
        select(JuncImageRequestLDST).where(JuncImageRequestLDST.ldst_id == hyp)
    ).all()


def verification_record(rec: ImageRecord):
    return {
        'verified': rec.verified,
        'pid': rec._pid,
        'gentime': rec.yamcs_generation_time.isoformat()[:19] + "Z",
        'req_id': None if rec.image_request is None else rec.image_request.id
    }


def request_info_record(req: ImageRequest):
    form = RequestForm(image_request=req)
    return {
        'vcode': form.verification_code,
        'ecode': form.eval_code,
        'status': req.status.name,
        'title': req.title,
        'critical': form.is_critical,
        'rec_ids': [rec.id for rec in req.image_records],
        'acquired': form.acquired,
        'pending_vis': form.pending_vis,
        'pending_eval': form.pending_eval,
        'evaluation_possible': form.evaluation_possible,
        'pending_evaluations': form.pending_evaluations
    }, form


def request_review_dict(session):
    return {
        req.id: request_info_record(req)[0]
        for req in session.scalars(select(ImageRequest)).all()
    }


def ldst_summary_dict(hyp_eval: dict, req_info: dict):
    summary = {
        'relevant': 0,
        'critical': 0,
        'acquired': 0,
        'pending_vis': 0,
        'pending_eval': 0,
        'passed': 0,
        'failed': 0
    }
    for req_id, status in hyp_eval.items():
        if status['relevant'] is True:
            summary['relevant'] += 1
        critical, acquired = status['critical'], req_info[req_id]['acquired']
        if critical is True:
            summary['critical'] += 1
        if acquired is True:
            summary['acquired'] += 1
        if not (acquired and critical):
            continue
        if req_info[req_id]['pending_vis'] is True:
            summary['pending_vis'] += 1
        elif status['pending_eval'] is True:
            summary['pending_eval'] += 1
        elif status['evaluation'] is True:
            summary['passed'] += 1
        elif status['evaluation'] is False:
            summary['failed'] += 1
        else:
            raise ValueError
    return summary


def ldst_status_dict(session):
    eval_by_req, eval_by_hyp, req_info = {}, NestingDict(), NestingDict()
    for req in session.scalars(select(ImageRequest)).all():
        req_info[req.id], form = request_info_record(req)
        eval_by_req[req.id] = form.eval_info
        for hyp, e in eval_by_req[req.id].items():
            eval_by_hyp[hyp][req.id]['relevant'] = e['relevant']
            eval_by_hyp[hyp][req.id]['critical'] = e['critical']
            eval_by_hyp[hyp][req.id]['evaluation'] = e['evaluation']
            eval_by_hyp[hyp][req.id]['pending_eval'] = (
                hyp in req_info[req.id]['pending_evaluations']
            )
    ldst_summary_info = {
        hyp: ldst_summary_dict(eval_by_hyp[hyp], req_info)
        for hyp in eval_by_hyp.keys()
    }
    return {
        'eval_by_req': eval_by_req,
        'eval_by_hyp': eval_by_hyp.todict(),
        'req_info': req_info.todict(),
        'ldst_summary_info': ldst_summary_info
    }


def verification_info_dict(session):
    return {
        rec.id: verification_record(rec)
        for rec in session.scalars(select(ImageRecord)).all()
    }


def review_info_dict(session):
    verifications = verification_info_dict(session)
    req_info = request_review_dict(session)
    for req_id, info in req_info.items():
        for rec_id in info['rec_ids']:
            verifications[rec_id]['req_id'] = req_id
            verifications[rec_id]['critical'] = info['critical']
    return {'req_info': req_info, 'verifications': verifications}


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

    last_image_ids = get_last_image_ids(session)
    records = []
    rows = session.scalars(select(ProtectedListEntry)).all()
    rows.sort(key=lambda r: r.request_time, reverse=True)
    for row in rows:
        record = {
            "ccu": row.ccu,
            "image_id": row.image_id,
            "request_time": row.request_time.isoformat()[:19] + "Z",
            "rationale": row.rationale,
            "pl_url": f"/plrequest?pl-id={row.pl_id}",
            "has_lossless": row.has_lossless,
            "superseded": row.superseded,
            "pid": row.request_pid,
        }
        records.append(record)
    return render(
        request,
        "pl_display.html",
        {
            "pl_json": json.dumps(records),
            "write_head": {'zero': last_image_ids[0], 'one': last_image_ids[1]},
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
    capturesets = image_request_capturesets()
    records = defaultdict(list)
    for row in rows:
        record = {
            "product_id": row.product_id,
            "capture_id": row.capture_id,
            "instrument": row.instrument_name,
            "image_url": DATA_URL + row.file_path,
            "label_url": DATA_URL + row.file_path.replace("tif", "json"),
            "thumbnail_url": BROWSE_URL
            + row.file_path.replace(".tif", "_thumb.jpg"),
            "image_request_name": "create",
            "image_request_url": "/imagerequest",
        }
        for req_id, captures in capturesets.items():
            if int(row.capture_id) in captures:
                record["image_request_name"] = "edit"
                record["image_request_url"] += f"?req_id={req_id}"
        if record["image_request_name"] == "create":
            # i.e., we didn't find an existing request
            record["image_request_url"] += f"?capture_id={row.capture_id}"
        records["all"].append(record)
        records[record["instrument"].split(" ")[0]].append(record)

    # TODO: paginate, preferably configurably
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
