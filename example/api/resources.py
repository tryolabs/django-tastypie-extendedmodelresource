from django.contrib.auth.models import User

from tastypie import fields

from models import Entry

from nested_resource import WithNestedModelResource


class UserResource(WithNestedModelResource):
    class Meta:
        queryset = User.objects.all()
        resource_name = 'user'

    class Nested:
        entries = fields.ToManyField('api.resources.EntryResource', 'entries')


class EntryResource(WithNestedModelResource):
    user = fields.ForeignKey(UserResource, 'user')

    class Meta:
        queryset = Entry.objects.all()
        resource_name = 'entry'
