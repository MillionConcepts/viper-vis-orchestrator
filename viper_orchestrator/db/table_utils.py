"""abstractions for ORM object queries and introspection."""
from __future__ import annotations

from operator import gt, lt
from typing import Collection, Union, Any, Optional, TYPE_CHECKING

from sqlalchemy import select, inspect, sql
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session, DeclarativeBase
from sqlalchemy.orm.decl_api import DeclarativeAttributeIntercept

from viper_orchestrator.db import OSession
from viper_orchestrator.db.session import autosession
from vipersci.vis.db.image_records import ImageRecord, ImageType
from vipersci.vis.db.image_requests import ImageRequest

if TYPE_CHECKING:
    from viper_orchestrator.orchtypes import MappedRow


def intsplit(comma_separated_numbers: str) -> set[int]:
    """convert string of comma-separated numbers into set of integers"""
    return set(map(int, comma_separated_numbers.split(",")))


def collstring(coll: Collection) -> str:
    return ",".join(map(str, coll))


def pk(obj: Union[type[MappedRow], MappedRow]) -> Union[str, tuple[str]]:
    """get the name of a SQLAlchemy table's primary key(s)"""
    if not isinstance(obj, DeclarativeAttributeIntercept):
        inspection = inspect(type(obj))
    else:
        inspection = inspect(obj)
    keys = [key.name for key in inspection.primary_key]
    if len(keys) > 1:
        return tuple(keys)
    return keys[0]


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
    table: type[MappedRow],
    value: Any,
    pivot: Optional[str] = None,
    session: Optional[Session] = None,
    strict: bool = False
) -> MappedRow:
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
        result = session.get(table, value)
    else:
        # noinspection PyTypeChecker
        scalars = session.scalars(
            select(table).where(getattr(table, pivot) == value)
        )
        result = getattr(scalars, "first" if strict is False else "one")()
    if result is None:
        raise NoResultFound
    return result


def delete_cascade(obj, junc_names: Collection[str] = (), session=None):
    for name in junc_names:
        relationship = getattr(
            obj.__mapper__.relationships, name
        )
        self_field = relationship.back_populates
        table = relationship.mapper.class_
        selector = select(table).where(getattr(table, self_field) == obj)
        scalars = session.scalars(selector).all()
        for s in scalars:
            session.delete(s)
    session.commit()
    session.delete(obj)
    session.commit()


@autosession
def delete_image_request(request=None, req_id=None, session=None):
    if request is None and req_id is None:
        raise TypeError
    if request is None:
        request = get_one(ImageRequest, req_id)
    delete_cascade(request, ("ldst_associations",), session=session)


@autosession
def iterquery(selector, column, descending=True, window=50, session=None):
    last_key = None
    ordering = f"{column.name} desc" if descending is True else column
    comparator = lt if descending is True else gt
    statement = selector.add_columns(column).order_by(sql.text(ordering))
    while True:
        query = statement
        if last_key is not None:
            query = query.filter(comparator(column, last_key))
        result = session.execute(query.limit(window))
        frozen = result.freeze()
        chunk = frozen().all()
        if not chunk:
            break
        result_width = len(chunk[0])
        last_key = chunk[-1][-1]
        yield frozen().columns(
            *list(range(0, result_width - 1))
        ).scalars().all()

