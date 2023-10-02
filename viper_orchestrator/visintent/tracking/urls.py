"""url routing configuration"""

from django.urls import path

from viper_orchestrator.visintent.tracking import views

urlpatterns = [
    path('imagerequest', views.imagerequest, name='imagerequest'),
    path('submitrequest', views.submitrequest, name='submitrequest'),
    path('success', views.requestsuccess, name='success'),
    path('imagelist', views.imagelist, name='imagelist'),
    path('requestlist', views.requestlist, name='requestlist'),
    path('assign_records_from_capture_id', views.assign_records_from_capture_id, name='assign_records_from_capture_id'),
    path('plrequest', views.plrequest, name='plrequest'),
    path('submitplrequest', views.submitplrequest, name='submitplrequest'),
    path('pllist', views.pllist, name='protectedlist'),
    path('', views.pages, name='landing'),
    path('pages', views.pages, name='pages')
]
