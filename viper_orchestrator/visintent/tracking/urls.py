"""url routing configuration"""

from django.urls import path

from viper_orchestrator.visintent.tracking import views

urlpatterns = [
    path('imagerequest', views.imagerequest, name='imagerequest'),
    path('submitrequest', views.submitrequest, name='submitrequest'),
    path('success', views.requestsuccess, name='success'),
    path('imagelist', views.imagelist, name='imagelist'),
    path('requestlist', views.requestlist, name='requestlist'),
    path('assigncaptures', views.assigncaptures, name='assigncaptures'),
    path('plrequest', views.plrequest, name='plrequest'),
    path('submitplrequest', views.submitplrequest, name='submitplrequest'),
    path('pllist', views.pllist, name='protectedlist'),
    path('', views.pages, name='landing'),
    path('pages', views.pages, name='pages')
]
