from django.http import HttpResponse
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.core.urlresolvers import get_script_prefix, resolve, Resolver404
from django.conf.urls.defaults import patterns, url, include

from tastypie import fields, http
from tastypie.bundle import Bundle
from tastypie.exceptions import NotFound, ImmediateHttpResponse
from tastypie.resources import ModelResource, ModelDeclarativeMetaclass, \
    ResourceOptions, convert_post_to_put
from tastypie.utils import trailing_slash


class ExtendedResourceOptions(ResourceOptions):

    def __new__(cls, meta=None):
        new_class = super(ExtendedResourceOptions, cls).__new__(cls, meta)

        url_id_attr = getattr(new_class, 'url_id_attribute', None)
        if url_id_attr is None:
            new_class.url_id_attribute = 'pk'
        else:
            new_class.url_id_attribute = url_id_attr

        return new_class


class ExtendedDeclarativeMetaclass(ModelDeclarativeMetaclass):

    def __new__(cls, name, bases, attrs):
        new_class = super(ExtendedDeclarativeMetaclass, cls).\
            __new__(cls, name, bases, attrs)

        opts = getattr(new_class, 'Meta', None)
        new_class._meta = ExtendedResourceOptions(opts)

        nested = getattr(new_class, 'Nested', None)
        nested_fields = {}

        if nested:
            for field in dir(nested):
                if not field.startswith('_'):
                    nested_fields[field] = getattr(nested, field)
                    nested_fields[field].contribute_to_class(new_class, field)

        new_class._nested = nested_fields

        return new_class


class WithNestedModelResource(ModelResource):

    __metaclass__ = ExtendedDeclarativeMetaclass

    def get_resource_uri(self, bundle_or_obj):
        """
        Handles generating a resource URI for a single resource.

        Override this function from ModelResource in case we want to use an
        attribute that is not the pk (but is unique) for the URIs (for example,
        a GUID).
        """
        kwargs = {
            'resource_name': self._meta.resource_name,
        }

        id_attr = self._meta.url_id_attribute

        if isinstance(bundle_or_obj, Bundle):
            kwargs[id_attr] = getattr(bundle_or_obj.obj, id_attr)
        else:
            kwargs[id_attr] = getattr(bundle_or_obj, id_attr)

        if self._meta.api_name is not None:
            kwargs['api_name'] = self._meta.api_name

        return self._build_reverse_url("api_dispatch_detail", kwargs=kwargs)

    def detail_actions(self):
        """
        Actions on the detail view.
        List of urls that can be append to the detail url

        Example:
        return [
            url(r"^show_schema/$", self.wrap_view('get_schema'),
                name="api_get_schema")
        ]
        """
        return []

    def nested(self, regex, view, name):
        """
        Function collecting nested urls under the detail view together
        """
        def nest(nested_name, field):
            return url(r"%s(?P<nested_name>%s)/$" % (regex, nested_name),
                       view, name=name)

        nested_urls = [nest(*item) for item in self._nested.items()]

        more_details = patterns('',
            (regex, include(self.detail_actions()))
        )
        return nested_urls + more_details

    def base_urls(self):
        """
        The standard URLs this ``Resource`` should respond to.
        """
        # Due to the way Django parses URLs, ``get_multiple``
        # won't work without a trailing slash.
        urls = [
            url(r"^%s$" % trailing_slash(),
                self.wrap_view('dispatch_list'),
                name="api_dispatch_list"),
            url(r"^/schema%s$" % trailing_slash(),
                self.wrap_view('get_schema'),
                name="api_get_schema"),
            url(r"^/set/(?P<pk_list>\w[\w/;-]*)/$",
                self.wrap_view('get_multiple'), name="api_get_multiple"),
            url(r"^/(?P<%s>\w[\w-]*)%s$" % (self._meta.url_id_attribute,
                                           trailing_slash()),
                self.wrap_view('dispatch_detail'), name="api_dispatch_detail")
        ]
        # Add urls to the nested resources
        urls.extend(
            self.nested(r"^/(?P<%s>\w[\w-]*)/" % self._meta.url_id_attribute,
                        self.wrap_view('dispatch_nested'),
                        "api_dispatch_nested")
        )

        return urls

    def check_parent_authorization(self, request, parent_object):
        """
        Allows the ``Authorization`` class to check if the request has
        permissions over the parent.
        """
        if hasattr(self._meta.authorization, 'is_authorized_parent'):
            return self._meta.authorization.is_authorized_parent(request,
                        parent_object)

        return True

    def parent_obj_get(self, request=None, **kwargs):
        """
        Same as ``obj_get`` but for the parent resource.

        Calls another function instead of apply_authorization_limits.
        """
        try:
            parent_object = self.get_object_list(request).get(**kwargs)

            # If I am not authorized for the parent
            if not self.check_parent_authorization(request, parent_object):
                stringified_kwargs = ', '.join(["%s=%s" % (k, v)
                                                for k, v in kwargs.items()])
                raise self._meta.object_class.DoesNotExist("Couldn't find an "
                        "instance of '%s' which matched '%s'." %
                        (self._meta.object_class.__name__, stringified_kwargs))

            return parent_object
        except ObjectDoesNotExist:
            return http.HttpNotFound()
        except MultipleObjectsReturned:
            return http.HttpMultipleChoices("More than one resource is found "
                                            "at this URI.")

    def parent_cached_obj_get(self, request=None, **kwargs):
        """
        Same as ``cached_obj_get`` but for the parent resource.
        """
        cache_key = self.generate_cache_key('detail', **kwargs)
        bundle = self._meta.cache.get(cache_key)

        if bundle is None:
            bundle = self.parent_obj_get(request=request, **kwargs)
            self._meta.cache.set(cache_key, bundle)

        return bundle

    def get_via_uri_resolver(self, uri):
        prefix = get_script_prefix()
        chomped_uri = uri

        if prefix and chomped_uri.startswith(prefix):
            chomped_uri = chomped_uri[len(prefix) - 1:]

        try:
            _view, _args, kwargs = resolve(chomped_uri)
        except Resolver404:
            raise NotFound("The URL provided '%s' was not a link to a valid "
                           "resource." % uri)

        return kwargs

    def get_nested_via_uri(self, uri, parent_resource,
                           parent_object, nested_name, request=None):
        """
        Same as ``get_via_uri`` but custom permission check for nested
        resources.
        """
        kwargs = self.get_via_uri_resolver(uri)
        return self.obj_get(nested_name=nested_name,
                            parent_resource=parent_resource,
                            parent_object=parent_object,
                            request=request,
                            **self.remove_api_resource_names(kwargs))

    def get_via_uri_no_auth_check(self, uri, request=None):
        """
        Same as ``get_via_uri`` but does NOT check any permissions.
        Those checks must be performed manually.
        """
        kwargs = self.get_via_uri_resolver(uri)
        return self.obj_get_no_auth_check(request=request,
                        **self.remove_api_resource_names(kwargs))

    def obj_get(self, request=None, **kwargs):
        """
        Same as ``obj_get`` but does custom check of permissions.
        """
        try:
            nested_name = kwargs.pop('nested_name', None)
            parent_resource = kwargs.pop('parent_resource', None)
            parent_object = kwargs.pop('parent_object', None)

            base_object_list = self.get_object_list(request).filter(**kwargs)

            if nested_name is not None:
                object_list = self.apply_nested_authorization_limits(request,
                                    nested_name, parent_resource,
                                    parent_object, base_object_list)
            else:
                object_list = self.apply_authorization_limits(request,
                                                              base_object_list)

            stringified_kwargs = ', '.join(["%s=%s" % (k, v)
                                            for k, v in kwargs.items()])

            if len(object_list) <= 0:
                raise self._meta.object_class.DoesNotExist("Couldn't find an "
                            "instance of '%s' which matched '%s'." %
                            (self._meta.object_class.__name__,
                             stringified_kwargs))
            elif len(object_list) > 1:
                raise MultipleObjectsReturned("More than '%s' matched '%s'." %
                        (self._meta.object_class.__name__, stringified_kwargs))

            return object_list[0]
        except ValueError:
            raise NotFound("Invalid resource lookup data provided (mismatched "
                           "type).")

    def obj_get_no_auth_check(self, request=None, **kwargs):
        """
        Same as ``obj_get`` but does NOT check for permissions.
        """
        try:
            object_list = self.get_object_list(request).filter(**kwargs)
            stringified_kwargs = ', '.join(["%s=%s" % (k, v)
                                            for k, v in kwargs.items()])

            if len(object_list) <= 0:
                raise self._meta.object_class.DoesNotExist("Couldn't find an "
                            "instance of '%s' which matched '%s'." %
                            (self._meta.object_class.__name__,
                             stringified_kwargs))
            elif len(object_list) > 1:
                raise MultipleObjectsReturned("More than '%s' matched '%s'." %
                        (self._meta.object_class.__name__, stringified_kwargs))

            return object_list[0]
        except ValueError:
            raise NotFound("Invalid resource lookup data provided (mismatched "
                           "type).")

    def apply_nested_authorization_limits(self, request, nested_name,
                                          parent_resource, parent_object,
                                          object_list):
        """
        Allows the ``Authorization`` class to further limit the object list.
        Also a hook to customize per ``Resource``.
        """
        method_name = 'apply_limits_nested_%s' % nested_name
        if hasattr(parent_resource._meta.authorization, method_name):
            method = getattr(parent_resource._meta.authorization, method_name)
            object_list = method(request, parent_object, object_list)

        return object_list

    @property
    def urls(self):
        """
        The endpoints this ``Resource`` responds to.

        Mostly a standard URLconf, this is suitable for either automatic use
        when registered with an ``Api`` class or for including directly in
        a URLconf should you choose to.
        """
        urls = self.override_urls() + self.base_urls()
        urls = patterns('', *urls)
        urlpatterns = patterns('',
            (r"^(?P<resource_name>%s)" % self._meta.resource_name,
                include(urls))
        )
        return urlpatterns

    def dispatch_nested(self, request, **kwargs):
        """
        Dispatch a request to the nested resource.
        """
        # We don't check for is_authorized here since it will be
        # parent_cached_obj_get which will check that we have permissions
        # over the parent.
        self.is_authenticated(request)
        self.throttle_check(request)

        nested_name = kwargs.pop('nested_name')
        nested_field = self._nested[nested_name]

        try:
            obj = self.parent_cached_obj_get(request=request,
                        **self.remove_api_resource_names(kwargs))
        except ObjectDoesNotExist:
            return http.HttpNotFound()
        except MultipleObjectsReturned:
            return http.HttpMultipleChoices("More than one resource is found.")

        kwargs.pop(self._meta.url_id_attribute)

        manager = None
        if isinstance(nested_field.attribute, basestring):
            name = nested_field.attribute
            manager = getattr(obj, name, None)
        elif callable(nested_field.attribute):
            manager = nested_field.attribute(obj)
        else:
            raise fields.ApiFieldError(
                "The model '%r' has an empty attribute '%s' \
                and doesn't allow a null value." % (
                    obj,
                    nested_field.attribute
                )
            )

        # The resource needs to get the api_name from their father because
        # the nested resource maybe isn't registered
        nested_resource = nested_field.to_class()
        nested_resource._meta.api_name = self._meta.api_name

        return nested_resource.dispatch(
            'list',
            request,
            nested_name=nested_name,
            parent_resource=self,
            parent_object=obj,
            related_manager=manager,
            **kwargs
        )

    def is_authorized_nested(self, request, nested_name,
                             parent_resource, parent_object, object=None):
        """
        Handles checking of permissions to see if the user has authorization
        to GET, POST, PUT, or DELETE this resource.  If ``object`` is provided,
        the authorization backend can apply additional row-level permissions
        checking.
        """
        # We use the authorization of the parent resource
        method_name = 'is_authorized_nested_%s' % nested_name
        if hasattr(parent_resource._meta.authorization, method_name):
            method = getattr(parent_resource._meta.authorization, method_name)
            auth_result = method(request, parent_object, object)

            if isinstance(auth_result, HttpResponse):
                raise ImmediateHttpResponse(response=auth_result)

            if not auth_result is True:
                raise ImmediateHttpResponse(response=http.HttpUnauthorized())

    def dispatch(self, request_type, request, **kwargs):
        """
        Same as the usual dispatch, but knows if its being called from a nested
        resource.
        """
        allowed_methods = getattr(self._meta,
                                  "%s_allowed_methods" % request_type, None)
        request_method = self.method_check(request, allowed=allowed_methods)

        method = getattr(self, "%s_%s" % (request_method, request_type), None)

        if method is None:
            raise ImmediateHttpResponse(response=http.HttpNotImplemented())

        self.is_authenticated(request)
        self.throttle_check(request)

        nested_name = kwargs.get('nested_name', None)
        parent_resource = kwargs.get('parent_resource', None)
        parent_object = kwargs.get('parent_object', None)
        if nested_name is None:
            self.is_authorized(request)
        else:
            self.is_authorized_nested(request, nested_name,
                                      parent_resource,
                                      parent_object)

        # All clear. Process the request.
        request = convert_post_to_put(request)
        response = method(request, **kwargs)

        # Add the throttled request.
        self.log_throttled_access(request)

        # If what comes back isn't a ``HttpResponse``, assume that the
        # request was accepted and that some action occurred. This also
        # prevents Django from freaking out.
        if not isinstance(response, HttpResponse):
            return http.HttpNoContent()

        return response

    def obj_create(self, bundle, request=None, **kwargs):
        related_manager = kwargs.pop('related_manager', None)
        # Remove the other parameters used for the nested resources, if they
        # are present.
        kwargs.pop('nested_name', None)
        kwargs.pop('parent_resource', None)
        kwargs.pop('parent_object', None)

        bundle.obj = self._meta.object_class()

        for key, value in kwargs.items():
            setattr(bundle.obj, key, value)

        bundle = self.full_hydrate(bundle)

        # Save FKs just in case.
        self.save_related(bundle)

        if related_manager is not None:
            related_manager.add(bundle.obj)

        # Save the main object.
        bundle.obj.save()

        # Now pick up the M2M bits.
        m2m_bundle = self.hydrate_m2m(bundle)
        self.save_m2m(m2m_bundle)
        return bundle

    def get_list(self, request, **kwargs):
        """
        Returns a serialized list of resources.

        Calls ``obj_get_list`` to provide the data, then handles that result
        set and serializes it.

        Should return a HttpResponse (200 OK).
        """
        if 'related_manager' in kwargs:
            manager = kwargs.pop('related_manager')
            base_objects = manager.all()

            nested_name = kwargs.pop('nested_name', None)
            parent_resource = kwargs.pop('parent_resource', None)
            parent_object = kwargs.pop('parent_object', None)

            objects = self.apply_nested_authorization_limits(request,
                            nested_name, parent_resource, parent_object,
                            base_objects)
        else:
            objects = self.obj_get_list(
                request=request,
                **self.remove_api_resource_names(kwargs)
            )

        sorted_objects = self.apply_sorting(objects, options=request.GET)

        paginator = self._meta.paginator_class(
            request.GET,
            sorted_objects,
            resource_uri=self.get_resource_list_uri(),
            limit=self._meta.limit
        )
        to_be_serialized = paginator.page()

        # Dehydrate the bundles in preparation for serialization.
        bundles = []
        for obj in to_be_serialized['objects']:
            bundles.append(
                self.full_dehydrate(
                    self.build_bundle(obj=obj, request=request)
                )
            )

        to_be_serialized['objects'] = bundles
        to_be_serialized = self.alter_list_data_to_serialize(request,
                                                             to_be_serialized)
        return self.create_response(request, to_be_serialized)

