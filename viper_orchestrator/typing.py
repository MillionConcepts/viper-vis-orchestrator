"""
general types defined for shared use. these make no intrinsic attempts to
avoid import cycles, and modules that import them in a way that produces
import cycles are responsible for using future.__annotations__, TYPE_CHECKING,
or other workarounds.
"""
from typing import Union, Mapping, Callable

from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST

from django.http import HttpResponse, HttpResponseRedirect


DjangoResponseType = Union[HttpResponse, HttpResponseRedirect]
AppTable = Union[ImageRequest, ImageRecord, ProtectedListEntry]
JuncTable = Union[JuncImageRecordTag, JuncImageRequestLDST]
AssociationRule = Mapping[
    str, Union[str, JuncTable, tuple[str], Callable[[], None]]
]
