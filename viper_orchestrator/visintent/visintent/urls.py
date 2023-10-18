from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include, re_path
from django.views.static import serve

# noinspection PyUnresolvedReferences
from viper_orchestrator import config

urlpatterns = [
    path("", include("viper_orchestrator.visintent.tracking.urls")),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
# TODO: again, maybe change this in prod
for filetype in ("BROWSE", "DATA", "REQUEST_FILE"):
    url = getattr(settings, f"{filetype}_URL")
    root = getattr(config, f"{filetype}_ROOT")
    urlpatterns.append(
        re_path(rf"^{url}(?P<path>.*)$", serve, {"document_root": root})
    )
