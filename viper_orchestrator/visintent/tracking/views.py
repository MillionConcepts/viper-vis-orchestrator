"""django view functions and helpers."""
import datetime as dt
import json
import shutil
from typing import Union

from cytoolz import groupby
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError

# noinspection PyUnresolvedReferences
from viper_orchestrator.config import DATA_ROOT, PRODUCT_ROOT
from viper_orchestrator.db import OSession
from viper_orchestrator.db.table_utils import (
    image_request_capturesets,
    get_capture_ids,
    get_record_ids,
    records_from_capture_ids,
)
from viper_orchestrator.visintent.tracking.db_utils import (
    _create_or_update_entry,
)
from viper_orchestrator.visintent.tracking.forms import (
    RequestForm,
    PLSubmission,
    BadURLError,
    AlreadyLosslessError,
    AlreadyDeletedError,
)
from viper_orchestrator.visintent.tracking.forms import (
    request_supplementary_path,
)
from viper_orchestrator.visintent.tracking.tables import (
    CCU_HASH,
    ProtectedListEntry,
)
from viper_orchestrator.visintent.visintent.settings import BROWSE_URL, \
    DATA_URL
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest


@never_cache
def image(request: WSGIRequest, **_regex_kwargs) -> HttpResponse:
    pid = request.path.strip("/")
    with OSession() as session:
        try:
            record = session.scalars(
                select(ImageRecord).where(ImageRecord._pid == pid)
            ).one()
        except InvalidRequestError:
            return HttpResponse(
                f"Sorry, no images exist in the database with product id "
                f"{pid}.",
                status=404,
            )
        label_path_stub = record.file_path.replace(".tif", ".json")
        with (DATA_ROOT / label_path_stub).open() as stream:
            metadata = json.load(stream)
        return render(
            request,
            "image_view.html",
            {
                "browse_url": (
                    BROWSE_URL
                    + record.file_path.replace(".tif", "_browse.jpg")
                ),
                "label_url": DATA_ROOT / label_path_stub,
                "image_url": record.file_path,
                "metadata": metadata,
                "pid": record._pid,
                "pagetitle": record._pid
                # TODO: verification link, blah blah blah
            },
        )


@never_cache
def imagerequest(request: WSGIRequest) -> HttpResponse:
    """render image request form page"""
    form = RequestForm.from_wsgirequest(request)
    editing = request.GET.get("editing", True)
    template = "image_request.html" if editing is True else "request_view.html"
    bound = {f.name: f.value for f in tuple(form)}
    # these variables are used only for non-editing display
    showpano = bound["camera_request"]() == "navcam_panorama"
    showslice = (bound["need_360"]() is True) and showpano
    if form.id is None and editing is False:
        return HttpResponse(
            "cannot generate view for nonexistent image request", status=400
        )
    filename, file_url = form.filepaths()
    try:
        return render(
            request,
            template,
            {
                "form": form,
                "showpano": showpano,
                "showslice": showslice,
                "filename": filename,
                "file_url": file_url,
                "pagetitle": "Image Request",
            },
        )
    except BadURLError as bue:
        return HttpResponse(str(bue), status=400)


@never_cache
def submitrequest(
    request: WSGIRequest,
) -> Union[HttpResponse, HttpResponseRedirect]:
    """
    handle request submission and redirect to errors or success notification
    as appropriate
    """
    request_id = request.POST.get("request_id")
    capture_id = request.POST.get("capture_id")
    form = RequestForm(
        request.POST, capture_id=capture_id, request_id=request_id
    )
    if form.is_valid() is False:
        return render(request, "image_request.html", {"form": form})
    with OSession() as session:
        try:
            pivot = "capture_id" if request_id is None else "id"
            row, associations = _create_or_update_entry(
                form,
                session,
                pivot,
                extra_attrs=(
                    "imaging_mode",
                    "camera_type",
                    "hazcams",
                    "generalities",
                ),
            )
            session.commit()
        except ValueError as ve:
            form.add_error(None, str(ve))
            return render(request, "image_request.html", {"form": form})
        if (fileobj := request.FILES.get("supplementary_file")) is not None:
            filepath = request_supplementary_path(row.id, fileobj.name)
            shutil.rmtree(filepath.parent, ignore_errors=True)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "wb") as stream:
                stream.write(fileobj.read())
    return redirect("/success")


@never_cache
def requestlist(request):
    """prep and render list of all existing requests"""
    with OSession() as session:
        rows = session.scalars(select(ImageRequest)).all()
        # noinspection PyUnresolvedReferences
        rows.sort(key=lambda r: r.request_time, reverse=True)
        records = []
        for row in rows:
            record = {
                "title": row.title,
                "request_time": row.request_time,
                "capture_id": get_capture_ids(row, as_str=True),
                "view_url": (
                    f"/imagerequest?request_id={row.id}&editing=false"
                ),
                "request_id": row.id,
                "pagetitle": "Image Request List",
            }
            records.append(record)
        # TODO: paginate, preferably configurably
    return render(request, "request_list.html", {"records": records})


@never_cache
def plrequest(request):
    """render pl request form page"""
    product_id, pl_id = (request.GET.get(k) for k in ("product-id", "pl-id"))
    if (product_id is None) and (pl_id is None):
        return render(request, "pl_landing.html")
    if product_id is not None:
        product_id = product_id.strip()
    try:
        form = PLSubmission(product_id=product_id, pl_id=pl_id)
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
    return render(
        request,
        "add_to_pl.html",
        {"form": form, "pagetitle": "Protected List Request"},
    )


@never_cache
def pllist(request):
    """
    prep and render list of all existing protected list entries, along with
    most recent downlinked image ID (memory location) for each CCU
    """
    feed, entries = ProtectedListEntry.feed()
    with OSession() as session:
        images = session.scalars(select(ImageRecord)).all()
    # noinspection PyUnresolvedReferences
    images.sort(key=lambda r: r.start_time, reverse=True)
    # noinspection PyUnresolvedReferences
    entries.sort(key=lambda r: r.image_id)
    by_ccu = groupby(lambda i: CCU_HASH[i.instrument_name], images)
    last_image_ids = {
        {0: "zero", 1: "one"}[ccu]: im[0].image_id + 1
        for ccu, im in by_ccu.items()
    }
    records = []
    for entry in entries:
        if entry.has_lossless or entry.superseded:
            continue
        record = {
            "image_id": entry.image_id,
            "request_time": entry.request_time,
            "rationale": entry.rationale,
            "ccu": entry.ccu,
            "pl_url": f"/plrequest?pl-id={entry.pl_id}",
            "pagetitle": "Protected List Display",
        }
        records.append(record)
    # TODO: paginate, preferably configurably
    return render(
        request,
        "pl_display.html",
        {"records": records, "last_ids": last_image_ids, "feed": feed},
    )


def submitplrequest(request):
    """
    handle pl request submission and redirect to error or success notification
    as appropriate
    """
    product_id, pl_id = (request.GET.get(k) for k in ("product_id", "pl_id"))
    if product_id is not None:
        product_id = product_id.strip()
    form = PLSubmission(request.GET, product_id=product_id, pl_id=pl_id)
    if form.is_valid() is False:
        return render(request, "add_to_pl.html", {"form": form})
    with OSession() as session:
        try:
            _create_or_update_entry(
                form, session, "pl_id", "from_pid", ("product_id",)
            )
            session.commit()
        except ValueError as ve:
            form.add_error(None, str(ve))
            return render(request, "add_to_pl.html", {"form": form})
    return redirect("/success")


def requestsuccess(request):
    """render request successful page"""
    return render(request, "request_successful.html")


@never_cache
def imagelist(request):
    """prep and render list of all existing images"""
    with OSession() as session:
        rows = session.scalars(select(ImageRecord)).all()
    # noinspection PyUnresolvedReferences
    rows.sort(key=lambda r: r.start_time, reverse=True)
    records, capturesets = [], image_request_capturesets()
    # noinspection PyTypeChecker
    for row in rows:
        record = {
            "product_id": row.product_id,
            "start_time": row.start_time,
            "creation_time": row.file_creation_datetime,
            "capture_id": row.capture_id,
            "instrument": row.instrument_name,
            "image_url": DATA_URL + row.file_path,
            "label_url": DATA_URL + row.file_path.replace("tif", "json"),
            "thumbnail_url": BROWSE_URL
            + row.file_path.replace(".tif", "_thumb.jpg"),
            "image_request_name": "create",
            "image_request_url": "/imagerequest",
        }
        for request_id, captures in capturesets.items():
            if int(row.capture_id) in captures:
                record["image_request_name"] = "edit"
                record["image_request_url"] += f"?request_id={request_id}"
        if record["image_request_name"] == "create":
            # i.e., we didn't find an existing request
            record["image_request_url"] += f"?capture_id={row.capture_id}"
        records.append(record)
    # TODO: paginate, preferably configurably
    return render(
        request,
        "image_list.html",
        {"records": records, "pagetitle": "Image List"},
    )


@never_cache
def assign_records_from_capture_ids(
    request: WSGIRequest,
) -> Union[HttpResponse, HttpResponseRedirect]:
    """(re)assign capture ids to an image request"""
    # TODO: better error messages
    cids = request.GET["capture-id"]
    cids = None if cids.lower() in ("none", "") else cids
    if cids is not None:
        try:
            cids = tuple(map(int, cids.replace(" ", "").strip(",").split(",")))
        except (ValueError, AttributeError, TypeError):
            return HttpResponse(
                "capture id(s) must be 'none' (case-insensitive), blank, a "
                "base-10 integer, or a comma-separated list of base-10 "
                "integers"
            )
    with OSession() as session:
        # noinspection PyTypeChecker
        selector = select(ImageRequest).where(
            request.GET["id"] == ImageRequest.id
        )
        # TODO, maybe: assign capture even if there are no imagerecords
        #  as of yet
        image_request = session.scalars(selector).one()
        records = records_from_capture_ids(cids, session)
        if get_record_ids(records) == get_record_ids(image_request):
            return redirect("/requestlist")
        try:
            image_request.image_records = records
            image_request.request_time = dt.datetime.now()
        except ValueError as ve:
            return HttpResponse(str(ve))
        session.commit()
    return redirect("/requestlist")


def pages(request):
    return render(request, "pages.html")
