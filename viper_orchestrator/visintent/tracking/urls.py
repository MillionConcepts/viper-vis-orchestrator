"""Django url routing configuration"""

from django.urls import path, re_path

from viper_orchestrator.visintent.tracking import views
from vipersci.pds.pid import vis_pid_re

urlpatterns = [
    path("imagerequest", views.imagerequest, name="imagerequest"),
    path("submitrequest", views.submitrequest, name="submitrequest"),
    path("success", views.requestsuccess, name="success"),
    path("imagelist", views.imagelist, name="imagelist"),
    path("requestlist", views.requestlist, name="requestlist"),
    path(
        "assign_records_from_capture_id",
        views.assign_records_from_capture_ids,
        name="assign_records_from_capture_id",
    ),
    path("plrequest", views.plrequest, name="plrequest"),
    path("submitplrequest", views.submitplrequest, name="submitplrequest"),
    path("pllist", views.pllist, name="protectedlist"),
    path("", views.pages, name="landing"),
    path("pages", views.pages, name="pages"),
    re_path(f"^{vis_pid_re.pattern}", views.imageview, name="image")
]
