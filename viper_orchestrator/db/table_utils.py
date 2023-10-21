"""abstractions for ORM object queries and introspection."""
from typing import Collection, Union, Any, Optional

from sqlalchemy import select, inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm._typing import _O

from viper_orchestrator.db import OSession
from viper_orchestrator.db.session import autosession
from vipersci.vis.db.image_records import ImageRecord, ImageType
from vipersci.vis.db.image_requests import ImageRequest


def intsplit(comma_separated_numbers: str) -> set[int]:
    """convert string of comma-separated numbers into set of integers"""
    return set(map(int, comma_separated_numbers.split(",")))


def collstring(coll: Collection) -> str:
    return ",".join(map(str, coll))


def pk(obj: Union[type[_O], _O]) -> str:
    return inspect(obj).primary_key[0].name


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


@autosession
def get_one(
    table: type[_O],
    value: Any,
    pivot: Optional[str] = None,
    session: Optional[Session] = None,
    strict: bool = False
) -> _O:
    """
    get a single row from a table based on strict equality between the
    `value` argument and the value of the field named `pivot` in the `table`.
    If `pivot` is None, this field to the first primary key of `table` (
        this operation is also more efficient with an already-open Session, as
        it can use the Session's pk cache.)
    If strict is True, will throw an error if more than one row matches the
        criterion; otherwise returns the top matching row.
    Will always throw a NoResultFound exception if no row is found.
    """
    if pivot is None:
        return session.get(table, value)
    # noinspection PyTypeChecker
    scalars = session.scalars(
        select(table).where(getattr(table, pivot) == value)
    )
    return getattr(scalars, "first" if strict is False else "one")()
