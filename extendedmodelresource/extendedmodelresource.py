from django.http import HttpResponse, HttpResponseBadRequest
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.core.urlresolvers import get_script_prefix, resolve, Resolver404
try:
    from django.conf.urls import patterns, url, include
except ImportError:
    from django.conf.urls.defaults import patterns, url, include

from tastypie import fields, http
from tastypie.exceptions import NotFound, ImmediateHttpResponse
from tastypie.resources import ResourceOptions, ModelDeclarativeMetaclass, \
    ModelResource, convert_post_to_put
from tastypie.utils import trailing_slash


class ExtendedDeclarativeMetaclass(ModelDeclarativeMetaclass):
    """
    Same as ``DeclarativeMetaclass`` but uses ``AnyIdAttributeResourceOptions``
    instead of ``ResourceOptions`` and adds support for multiple nested fields
    defined in a "Nested" class (the same way as "Meta") inside the resources.
    """

    def __new__(cls, name, bases, attrs):
        new_class = super(ExtendedDeclarativeMetaclass, cls).__new__(cls,
                            name, bases, attrs)

        opts = getattr(new_class, 'Meta', None)
        new_class._meta = ResourceOptions(opts)

        # Will map nested fields names to the actual fields
        nested_fields = {}

        nested_class = getattr(new_class, 'Nested', None)
        if nested_class is not None:
            for field_name in dir(nested_class):
                if not field_name.startswith('_'):  # No internals
                    field_object = getattr(nested_class, field_name)

                    nested_fields[field_name] = field_object
                    if hasattr(field_object, 'contribute_to_class'):
                        field_object.contribute_to_class(new_class,
                                                         field_name)

        new_class._nested = nested_fields

        return new_class


class ExtendedModelResource(ModelResource):

    __metaclass__ = ExtendedDeclarativeMetaclass

    def remove_api_resource_names(self, url_dict):
        """
        Override this function, we are going to use some data for Nesteds.
        """
        return url_dict.copy()

    def real_remove_api_resource_names(self, url_dict):
        """
        Given a dictionary of regex matches from a URLconf, removes
        ``api_name`` and/or ``resource_name`` if found.

        This is useful for converting URLconf matches into something suitable
        for data lookup. For example::

            Model.objects.filter(**self.remove_api_resource_names(matches))
        """
        kwargs_subset = url_dict.copy()

        for key in ['api_name', 'resource_name', 'related_manager',
                    'child_object', 'parent_resource', 'nested_name',
                    'parent_object']:
            try:
                del(kwargs_subset[key])
            except KeyError:
                pass

        return kwargs_subset

    def get_detail_uri_name_regex(self):
        """
        Return the regular expression to which the id attribute used in
        resource URLs should match.

        By default we admit any alphanumeric value and "-", but you may
        override this function and provide your own.
        """
        return r'\w[\w-]*'

    def base_urls(self):
        """
        Same as the original ``base_urls`` but supports using the custom
        regex for the ``detail_uri_name`` attribute of the objects.
        """
        # Due to the way Django parses URLs, ``get_multiple``
        # won't work without a trailing slash.
        return [
            url(r"^(?P<resource_name>%s)%s$" %
                    (self._meta.resource_name, trailing_slash()),
                    self.wrap_view('dispatch_list'),
                    name="api_dispatch_list"),
            url(r"^(?P<resource_name>%s)/schema%s$" %
                    (self._meta.resource_name, trailing_slash()),
                    self.wrap_view('get_schema'),
                    name="api_get_schema"),
            url(r"^(?P<resource_name>%s)/set/(?P<%s_list>(%s;?)*)/$" %
                    (self._meta.resource_name,
                     self._meta.detail_uri_name,
                     self.get_detail_uri_name_regex()),
                    self.wrap_view('get_multiple'),
                    name="api_get_multiple"),
            url(r"^(?P<resource_name>%s)/(?P<%s>%s)%s$" %
                    (self._meta.resource_name,
                     self._meta.detail_uri_name,
                     self.get_detail_uri_name_regex(),
                     trailing_slash()),
                     self.wrap_view('dispatch_detail'),
                     name="api_dispatch_detail"),
        ]

    def nested_urls(self):
        """
        Return the list of all urls nested under the detail view of a resource.

        Each resource listed as Nested will generate one url.
        """
        def get_nested_url(nested_name):
            return url(r"^(?P<resource_name>%s)/(?P<%s>%s)/"
                        r"(?P<nested_name>%s)%s$" %
                       (self._meta.resource_name,
                        self._meta.detail_uri_name,
                        self.get_detail_uri_name_regex(),
                        nested_name,
                        trailing_slash()),
                       self.wrap_view('dispatch_nested'),
                       name='api_dispatch_nested')

        return [get_nested_url(nested_name)
                for nested_name in self._nested.keys()]

    def detail_actions(self):
        """
        Return urls of custom actions to be performed on the detail view of a
        resource. These urls will be appended to the url of the detail view.
        This allows a finer control by providing a custom view for each of
        these actions in the resource.

        A resource should override this method and provide its own list of
        detail actions urls, if needed.

        For example:

        return [
            url(r"^show_schema/$", self.wrap_view('get_schema'),
                name="api_get_schema")
        ]

        will add show schema capabilities to a detail resource URI (ie.
        /api/user/3/show_schema/ will work just like /api/user/schema/).
        """
        return []

    def detail_actions_urlpatterns(self):
        """
        Return the url patterns corresponding to the detail actions available
        on this resource.
        """
        if self.detail_actions():
            detail_url = "^(?P<resource_name>%s)/(?P<%s>%s)/" % (
                            self._meta.resource_name,
                            self._meta.detail_uri_name,
                            self.get_detail_uri_name_regex()
            )
            return patterns('', (detail_url, include(self.detail_actions())))

        return []

    @property
    def urls(self):
        """
        The endpoints this ``Resource`` responds to.

        Same as the original ``urls`` attribute but supports nested urls as
        well as detail actions urls.
        """
        urls = self.prepend_urls() + self.base_urls() + self.nested_urls()
        return patterns('', *urls) + self.detail_actions_urlpatterns()

    def is_authorized_over_parent(self, request, parent_object):
        """
        Allows the ``Authorization`` class to check if a request to a nested
        resource has permissions over the parent.

        Will call the ``is_authorized_parent`` function of the
        ``Authorization`` class.
        """
        if hasattr(self._meta.authorization, 'is_authorized_parent'):
            return self._meta.authorization.is_authorized_parent(request,
                        parent_object)

        return True

    def parent_obj_get(self, request=None, **kwargs):
        """
        Same as the original ``obj_get`` but called when a nested resource
        wants to get its parent.

        Will check authorization to see if the request is allowed to act on
        the parent resource.
        """
        kwargs = self.real_remove_api_resource_names(kwargs)
        parent_object = self.get_object_list(request).get(**kwargs)

        # If I am not authorized for the parent
        if not self.is_authorized_over_parent(request, parent_object):
            stringified_kwargs = ', '.join(["%s=%s" % (k, v)
                                            for k, v in kwargs.items()])
            raise self._meta.object_class.DoesNotExist("Couldn't find an "
                    "instance of '%s' which matched '%s'." %
                    (self._meta.object_class.__name__, stringified_kwargs))

        return parent_object

    def parent_cached_obj_get(self, request=None, **kwargs):
        """
        Same as the original ``cached_obj_get`` but called when a nested
        resource wants to get its parent.
        """
        cache_key = self.generate_cache_key('detail', **kwargs)
        bundle = self._meta.cache.get(cache_key)

        if bundle is None:
            bundle = self.parent_obj_get(request=request, **kwargs)
            self._meta.cache.set(cache_key, bundle)

        return bundle

    def get_via_uri_resolver(self, uri):
        """
        Do the work of the original ``get_via_uri`` except calling ``obj_get``.

        Use this as a helper function.
        """
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
        Obtain a nested resource from an uri, a parent resource and a parent
        object.

        Calls ``obj_get`` which handles the authorization checks.
        """
        # TODO: improve this to get parent resource & object from uri too?
        kwargs = self.get_via_uri_resolver(uri)
        return self.obj_get(nested_name=nested_name,
                            parent_resource=parent_resource,
                            parent_object=parent_object,
                            request=request,
                            **self.remove_api_resource_names(kwargs))

    def get_via_uri_no_auth_check(self, uri, request=None):
        """
        Obtain a nested resource from an uri, a parent resource and a
        parent object.

        Does *not* do authorization checks, those must be performed manually.
        This function is useful be called from custom views over a resource
        which need access to objects and can do the check of permissions
        theirselves.
        """
        kwargs = self.get_via_uri_resolver(uri)
        return self.obj_get_no_auth_check(request=request,
                        **self.remove_api_resource_names(kwargs))

    def obj_get_list(self, request=None, **kwargs):
        """
        A ORM-specific implementation of ``obj_get_list``.

        Takes an optional ``request`` object, whose ``GET`` dictionary can be
        used to narrow the query.
        """
        filters = {}

        if hasattr(request, 'GET'):
            # Grab a mutable copy.
            filters = request.GET.copy()

        # Update with the provided kwargs.
        filters.update(self.real_remove_api_resource_names(kwargs))
        applicable_filters = self.build_filters(filters=filters)

        try:
            base_object_list = self.apply_filters(request, applicable_filters)
            return self.apply_proper_authorization_limits(request,
                                                base_object_list, **kwargs)
        except ValueError:
            raise HttpResponseBadRequest("Invalid resource lookup data provided "
                                         "(mismatched type).")

    def obj_get(self, request=None, **kwargs):
        """
        Same as the original ``obj_get`` but knows when it is being called to
        get an object from a nested resource uri.

        Performs authorization checks in every case.
        """
        try:
            base_object_list = self.get_object_list(request).filter(
                                **self.real_remove_api_resource_names(kwargs))

            object_list = self.apply_proper_authorization_limits(request,
                                                base_object_list, **kwargs)

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

    def cached_obj_get(self, request=None, **kwargs):
        """
        A version of ``obj_get`` that uses the cache as a means to get
        commonly-accessed data faster.
        """
        cache_key = self.generate_cache_key('detail',
                                **self.real_remove_api_resource_names(kwargs))
        bundle = self._meta.cache.get(cache_key)

        if bundle is None:
            bundle = self.obj_get(request=request, **kwargs)
            self._meta.cache.set(cache_key, bundle)

        return bundle

    def obj_create(self, bundle, request=None, **kwargs):
        """
        A ORM-specific implementation of ``obj_create``.
        """
        kwargs = self.real_remove_api_resource_names(kwargs)
        return super(ExtendedModelResource, self).obj_create(bundle, request,
                                                             **kwargs)

    def obj_update(self, bundle, request=None, skip_errors=False, **kwargs):
        """
        A ORM-specific implementation of ``obj_update``.
        """
        kwargs = self.real_remove_api_resource_names(kwargs)
        return super(ExtendedModelResource, self).obj_update(bundle, request,
                                            skip_errors=skip_errors, **kwargs)

    def obj_delete_list(self, request=None, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete_list``.

        Takes optional ``kwargs``, which can be used to narrow the query.
        """
        base_object_list = self.get_object_list(request).filter(
                                **self.real_remove_api_resource_names(kwargs))
        authed_object_list = self.apply_proper_authorization_limits(request,
                                                    base_object_list, **kwargs)

        if hasattr(authed_object_list, 'delete'):
            # It's likely a ``QuerySet``. Call ``.delete()`` for efficiency.
            authed_object_list.delete()
        else:
            for authed_obj in authed_object_list:
                authed_obj.delete()

    def obj_delete(self, request=None, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete``.

        Takes optional ``kwargs``, which are used to narrow the query to find
        the instance.
        """
        kwargs = self.real_remove_api_resource_names(kwargs)
        obj = kwargs.pop('_obj', None)

        if not hasattr(obj, 'delete'):
            try:
                obj = self.obj_get(request, **kwargs)
            except ObjectDoesNotExist:
                raise NotFound("A model instance matching the provided arguments could not be found.")

        obj.delete()

    def obj_get_no_auth_check(self, request=None, **kwargs):
        """
        Same as the original ``obj_get`` knows when it is being called to get
        a nested resource.

        Does *not* do authorization checks.
        """
        # TODO: merge this and original obj_get and use another argument in
        #       kwargs to know if we should check for auth?
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

    def apply_nested_authorization_limits(self, request, object_list,
                                               parent_resource, parent_object,
                                               nested_name):
        """
        Allows the ``Authorization`` class to further limit the object list.
        Also a hook to customize per ``Resource``.
        """
        method_name = 'apply_limits_nested_%s' % nested_name
        if hasattr(parent_resource._meta.authorization, method_name):
            method = getattr(parent_resource._meta.authorization, method_name)
            object_list = method(request, parent_object, object_list)

        return object_list

    def apply_proper_authorization_limits(self, request, object_list,
                                              **kwargs):
        """
        Decide which type of authorization to apply, if the resource is being
        used as nested or not.
        """
        parent_resource = kwargs.get('parent_resource', None)
        if parent_resource is None:  # No parent, used normally
            return self.apply_authorization_limits(request, object_list)

        # Used as nested!
        return self.apply_nested_authorization_limits(request, object_list,
                    parent_resource,
                    kwargs.get('parent_object', None),
                    kwargs.get('nested_name', None))

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
            return http.HttpMultipleChoices("More than one parent resource is "
                                            "found at this URI.")

        # The nested resource needs to get the api_name from its parent because
        # it is possible that the resource being used as nested is not
        # registered in the API (ie. it can only be used as nested)
        nested_resource = nested_field.to_class()
        nested_resource._meta.api_name = self._meta.api_name

        # TODO: comment further to make sense of this block
        manager = None
        try:
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
        except ObjectDoesNotExist:
            pass

        kwargs['nested_name'] = nested_name
        kwargs['parent_resource'] = self
        kwargs['parent_object'] = obj

        if manager is None or not hasattr(manager, 'all'):
            dispatch_type = 'detail'
            kwargs['child_object'] = manager
        else:
            dispatch_type = 'list'
            kwargs['related_manager'] = manager
            # 'pk' will refer to the parent, so we remove it.
            if 'pk' in kwargs:
                del kwargs['pk']
            # Update with the related manager's filters, which will link to
            # the parent.
            kwargs.update(manager.core_filters)

        return nested_resource.dispatch(
            dispatch_type,
            request,
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

        parent_resource = kwargs.get('parent_resource', None)
        if parent_resource is None:
            self.is_authorized(request)
        else:
            self.is_authorized_nested(request, kwargs['nested_name'],
                                      parent_resource,
                                      kwargs['parent_object'])

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

    def get_detail(self, request, **kwargs):
        """
        Returns a single serialized resource.

        Calls ``cached_obj_get/obj_get`` to provide the data, then handles that
        result set and serializes it.

        Should return a HttpResponse (200 OK).
        """
        try:
            # If call was made through Nested we should already have the
            # child object.
            if 'child_object' in kwargs:
                obj = kwargs.pop('child_object', None)
                if obj is None:
                    return http.HttpNotFound()
            else:
                obj = self.cached_obj_get(request=request,
                                    **self.remove_api_resource_names(kwargs))
        except AttributeError:
            return http.HttpNotFound()
        except ObjectDoesNotExist:
            return http.HttpNotFound()
        except MultipleObjectsReturned:
            return http.HttpMultipleChoices("More than one resource is found "
                                            "at this URI.")

        bundle = self.build_bundle(obj=obj, request=request)
        bundle = self.full_dehydrate(bundle)
        bundle = self.alter_detail_data_to_serialize(request, bundle)
        return self.create_response(request, bundle)

    def post_list(self, request, **kwargs):
        """
        Unsupported if used as nested. Otherwise, same as original.
        """
        if 'parent_resource' in kwargs:
            raise NotImplementedError('You cannot post a list on a nested'
                                      ' resource.')

        # TODO: support this & link with the parent (consider core_filters of
        #       the related manager to know which attribute to set.
        return super(ExtendedModelResource, self).post_list(request, **kwargs)

    def put_list(self, request, **kwargs):
        """
        Unsupported if used as nested. Otherwise, same as original.
        """
        if 'parent_resource' in kwargs:
            raise NotImplementedError('You cannot put a list on a nested'
                                      ' resource.')
        return super(ExtendedModelResource, self).put_list(request, **kwargs)

    def patch_list(self, request, **kwargs):
        """
        Unsupported if used as nested. Otherwise, same as original.
        """
        if 'parent_resource' in kwargs:
            raise NotImplementedError('You cannot patch a list on a nested'
                                      ' resource.')
        return super(ExtendedModelResource, self).patch_list(request, **kwargs)

