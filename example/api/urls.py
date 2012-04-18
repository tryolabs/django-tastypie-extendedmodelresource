from tastypie.api import Api

from api.resources import UserResource, EntryResource, UserByNameResource


v1_api = Api(api_name='v1')
v1_api.register(UserResource())
v1_api.register(EntryResource())
v1_api.register(UserByNameResource())
