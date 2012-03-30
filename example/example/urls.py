from django.conf.urls.defaults import *
from django.contrib import admin

from api.resources import EntryResource, UserResource


entry_resource = EntryResource()
user_resource = UserResource()

admin.autodiscover()

urlpatterns = patterns('',
    (r'^api/', include(entry_resource.urls)),
    (r'^api/', include(user_resource.urls)),
    url(r'^admin/', include(admin.site.urls)),
)
