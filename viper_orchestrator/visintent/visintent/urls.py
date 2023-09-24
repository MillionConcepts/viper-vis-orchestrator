from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include, re_path
from django.views.static import serve

urlpatterns = [
    path('', include('viper_orchestrator.visintent.tracking.urls')),
]


urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
# TODO: again, maybe change this in prod
urlpatterns += [
    re_path(
        rf"^{settings.MEDIA_URL[1:]}(?P<path>.*)$",
        serve,
        {
            "document_root": settings.MEDIA_ROOT,
        },
    ),
]