from django.conf.urls import url
from django.conf.urls.defaults import patterns, include
from django.contrib import admin

from api.urls import v1_api


admin.autodiscover()

urlpatterns = patterns('',
    url(r'^admin/', include(admin.site.urls)),
    (r"^api/", include(v1_api.urls)),
)
