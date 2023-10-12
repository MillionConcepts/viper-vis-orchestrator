"""abstractions for ORM object queries and introspection."""
from typing import Collection, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from viper_orchestrator.db import OSession
from vipersci.vis.db.image_records import ImageRecord, ImageType
from vipersci.vis.db.image_requests import ImageRequest


def intsplit(comma_separated_numbers: str) -> set[int]:
    """convert string of comma-separated numbers into set of integers"""
    return set(map(int, comma_separated_numbers.split(",")))


def collstring(coll: Collection) -> str:
    return ",".join(map(str, coll))


def get_record_attrs(
    recs: Union[ImageRequest, Collection[ImageRecord]],
    attr: str,
    as_str: bool = False
) -> Union[set, str]:
    if isinstance(recs, ImageRequest):
        recs = recs.image_records
    if as_str is False:
        return {getattr(r, attr) for r in recs}
    return collstring({getattr(r, attr) for r in recs})


def get_capture_ids(
    recs: Union[ImageRequest, Collection[ImageRecord]], as_str: bool = False
) -> Union[set[int], str]:
    return get_record_attrs(recs, "capture_id", as_str)


def get_record_ids(
    recs: Union[ImageRequest, Collection[ImageRecord]], as_str: bool = False
) -> Union[set[int], str]:
    return get_record_attrs(recs, "id", as_str)


def image_request_capturesets():
    capture_sets = {}
    with OSession() as session:
        requests = session.scalars(select(ImageRequest)).all()
        for request in requests:
            capture_sets[request.id] = set(
                map(lambda i: i.capture_id, request.image_records)
            )
    return capture_sets


def has_lossless(products: Collection[ImageRecord]) -> bool:
    """are any of these ImageRecords lossless?"""
    return any(
        ImageType(p.output_image_mask).name.startswith("LOSSLESS")
        for p in products
    )


def capture_ids_to_product_ids(
    cids: int | str | Collection[int | str]
) -> set[str]:
    if isinstance(cids, str):
        cids = map(int, cids.split(","))
    elif isinstance(cids, int):
        cids = {cids}
    else:
        cids = map(int, cids)
    pids = []
    with OSession() as session:
        for cid in cids:
            # noinspection PyTypeChecker
            selector = select(ImageRecord).where(ImageRecord.capture_id == cid)
            pids += [p.product_id for p in session.scalars(selector).all()]
    return set(pids)


def records_from_capture_ids(
    cids: Collection[int], session: Session
) -> list[ImageRecord]:
    """get all ImageRecords who belong to any of the captures in cids."""
    records = []
    if cids is None:
        return []
    for cid in cids:
        selector = select(ImageRecord).where(cid == ImageRecord.capture_id)
        records += session.scalars(selector).all()
    return records
