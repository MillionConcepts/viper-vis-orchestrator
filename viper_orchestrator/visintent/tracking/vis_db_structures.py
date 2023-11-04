"""
functions for formatting data about VIS db DeclarativeBase instances for
exchange.
"""
from typing import Union, MutableMapping, Any

from dustgoggles.structures import NestingDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from viper_orchestrator.visintent.tracking.forms import RequestForm
from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from viper_orchestrator.visintent.visintent.settings import (
    DATA_URL,
    BROWSE_URL,
)
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST

# type alias for objects intended to be sent to frontend as JSON.
sharedJSONType = MutableMapping[Union[str, int], Any]
# all names correspond to typedefs in vis_db_structures.js.
evaluationRecord = sharedJSONType
verificationRecord = sharedJSONType
reqInfoRecord = sharedJSONType
ldstEvalSummary = sharedJSONType
protectedListRecord = sharedJSONType
imageRecBrief = sharedJSONType


def _get_hyps(hyp, session):
    # noinspection PyTypeChecker
    return session.scalars(
        select(JuncImageRequestLDST).where(JuncImageRequestLDST.ldst_id == hyp)
    ).all()


def verification_record(rec: ImageRecord) -> verificationRecord:
    return {
        "verified": rec.verified,
        "pid": rec._pid,
        "gentime": rec.yamcs_generation_time.isoformat()[:19] + "Z",
        "req_id": None if rec.image_request is None else rec.image_request.id,
    }


def req_info_record(req: ImageRequest) -> tuple[reqInfoRecord, RequestForm]:
    form = RequestForm(image_request=req)
    return {
        "vcode": form.verification_code,
        "ecode": form.ecode,
        "status": req.status.name,
        "title": req.title,
        "critical": form.is_critical,
        "rec_ids": [rec.id for rec in req.image_records],
        "rec_pids": [rec._pid for rec in req.image_records],
        "acquired": form.acquired,
        "pending_vis": form.pending_vis,
        "pending_eval": form.pending_eval,
        "evaluation_possible": form.evaluation_possible,
        "pending_evaluations": form.pending_evaluations,
        "edit_url": f"imagerequest?req_id={form.req_id}",
        "request_time": req.request_time.isoformat()[:19] + "Z",
        "justification": req.justification,
        "req_id": req.id
    }, form


def request_review_dict(session) -> dict[int, reqInfoRecord]:
    return {
        req.id: req_info_record(req)[0]
        for req in session.scalars(select(ImageRequest)).all()
    }


def ldst_eval_summary(hyp_eval: dict, req_info: dict) -> ldstEvalSummary:
    summary = {
        "relevant": 0,
        "critical": 0,
        "acquired": 0,
        "pending_vis": 0,
        "pending_eval": 0,
        "passed": 0,
        "failed": 0,
    }
    for req_id, status in hyp_eval.items():
        if status["relevant"] is True:
            summary["relevant"] += 1
        critical, acquired = status["critical"], req_info[req_id]["acquired"]
        if critical is True:
            summary["critical"] += 1
        if not status["relevant"]:
            continue
        if acquired is True:
            summary["acquired"] += 1
        if not (acquired and critical):
            continue
        if req_info[req_id]["pending_vis"] is True:
            summary["pending_vis"] += 1
        elif status["pending_eval"] is True:
            summary["pending_eval"] += 1
        elif status["evaluation"] is True:
            summary["passed"] += 1
        elif status["evaluation"] is False:
            summary["failed"] += 1
        else:
            raise ValueError
    return summary


def ldst_status_dict(session: Session):
    eval_by_req, eval_by_hyp, req_info = {}, NestingDict(), NestingDict()
    for req in session.scalars(select(ImageRequest)).all():
        req_info[req.id], form = req_info_record(req)
        eval_by_req[req.id] = form.eval_info
        for hyp, e in eval_by_req[req.id].items():
            eval_by_hyp[hyp][req.id]["relevant"] = e["relevant"]
            eval_by_hyp[hyp][req.id]["critical"] = e["critical"]
            eval_by_hyp[hyp][req.id]["evaluation"] = e["evaluation"]
            eval_by_hyp[hyp][req.id]["pending_eval"] = (
                hyp in req_info[req.id]["pending_evaluations"]
            )
    ldst_summary_info = {
        hyp: ldst_eval_summary(eval_by_hyp[hyp], req_info)
        for hyp in eval_by_hyp.keys()
    }
    return {
        "eval_by_req": eval_by_req,  # evaluationRecords
        "eval_by_hyp": eval_by_hyp.todict(),  # also evaluationRecords
        "req_info": req_info.todict(),  # reqInfoRecords
        "ldst_summary_info": ldst_summary_info,  # ldstEvalSummaries
    }


def verification_info_dict(session) -> dict[int, verificationRecord]:
    return {
        rec.id: verification_record(rec)
        for rec in session.scalars(select(ImageRecord)).all()
    }


def review_info_dict(session: Session):
    verifications = verification_info_dict(session)  # verificationRecords
    req_info = request_review_dict(session)  # reqInfoRecords
    for req_id, info in req_info.items():
        for rec_id in info["rec_ids"]:
            verifications[rec_id]["req_id"] = req_id
            verifications[rec_id]["critical"] = info["critical"]
    return {"req_info": req_info, "verifications": verifications}


def rec_file_links(rec: ImageRecord):
    return {
        "image_url": DATA_URL + rec.file_path,
        "label_url": DATA_URL + rec.file_path.replace("tif", "json"),
        "thumbnail_url": BROWSE_URL
        + rec.file_path.replace(".tif", "_thumb.jpg"),
    }


def image_rec_brief(rec: ImageRecord) -> imageRecBrief:
    return {
        "product_id": rec.product_id,
        "instrument": rec.instrument_name,
        **rec_file_links(rec)
    }


def protected_list_record(row: ProtectedListEntry) -> protectedListRecord:
    # protectedListRecord
    return {
        "ccu": row.ccu,
        "image_id": row.image_id,
        "request_time": row.request_time.isoformat()[:19] + "Z",
        "rationale": row.rationale,
        "pl_url": f"/plrequest?pl_id={row.pl_id}",
        "has_lossless": row.has_lossless,
        "superseded": row.superseded,
        "pid": row.request_pid,
    }
