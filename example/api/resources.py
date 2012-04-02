from django.contrib.auth.models import User

from tastypie import fields

from models import Entry

from extended_resource import ExtendedModelResource


class UserResource(ExtendedModelResource):
    class Meta:
        queryset = User.objects.all()
        resource_name = 'user'

    class Nested:
        entries = fields.ToManyField('api.resources.EntryResource', 'entries')


class EntryResource(ExtendedModelResource):
    user = fields.ForeignKey(UserResource, 'user')

    class Meta:
        queryset = Entry.objects.all()
        resource_name = 'entry'
