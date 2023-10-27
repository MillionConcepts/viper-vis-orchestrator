"""
general types defined for shared use. these make no intrinsic attempts to
avoid import cycles, and modules that import them in a way that produces
import cycles are responsible for using future.__annotations__, TYPE_CHECKING,
or other workarounds.
"""
from __future__ import annotations
from typing import Union, Mapping, Callable

from django.http import HttpResponse, HttpResponseRedirect
from sqlalchemy.orm._typing import _O

from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST


DjangoResponseType = Union[HttpResponse, HttpResponseRedirect]
"""valid, in-use return types for django view functions"""

AppTable = Union[ImageRequest, ImageRecord, ProtectedListEntry]
"""non-junc tables we interact with at runtime"""

JuncRow = Union[JuncImageRecordTag, JuncImageRequestLDST]
"""junc (many-to-many relation manager) tables we interact with at runtime"""

JuncRule = Mapping[str, Union[str, JuncRow, tuple[str], Callable[[], None]]]
"""rules used to define the behavior of forms that manage relations"""

MappedRow = _O
"""
a SQLAlchemy mapped DeclarativeBase instance. 
alias for sqlalchemy.orm._typing._O
"""
