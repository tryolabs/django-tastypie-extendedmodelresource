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
    """
    A configuration class for ``ExtendedModelResource``.

    Adds the ability to use an attribute in the URLs of the resources different
    than the primary key of the objects.

    Useful for the case in which you want to hide the primary key of the
    objects in the database. For example, you may want to use an UUID to
    identify resources in a URL so the user cannot simply increment an integer
    key and attempt to gain access to another object.

    Any field you with to use as identifier for the objects in the URIs must
    have unique=True constraint.

    To use this you must declare an ``url_id_attribute`` in the resource with
    the name of the attribute that will identify the objects in the URI.
    If you have a 'uuid' attribute in the model, you then should declare

        url_id_attribute = 'uuid'

    in the corresponding resource.

    If the ``url_id_attribute`` field is not found, the object's pkey will be
    used as default.
    """
    def __new__(cls, meta=None):
        new_class = super(ExtendedResourceOptions, cls).__new__(cls, meta)

        new_class.url_id_attribute = getattr(new_class,
                                             'url_id_attribute',
                                             'pk')  # Defaults to pkey
        return new_class


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
        new_class._meta = ExtendedResourceOptions(opts)

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

    def get_url_id_attribute_regex(self):
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
        url_id_attribute instead of the pk of the objects.
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
                     self._meta.url_id_attribute,
                     self.get_url_id_attribute_regex()),
                    self.wrap_view('get_multiple'),
                    name="api_get_multiple"),
            url(r"^(?P<resource_name>%s)/(?P<%s>%s)%s$" %
                    (self._meta.resource_name,
                     self._meta.url_id_attribute,
                     self.get_url_id_attribute_regex(),
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
                        self._meta.url_id_attribute,
                        self.get_url_id_attribute_regex(),
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
                            self._meta.url_id_attribute,
                            self.get_url_id_attribute_regex()
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
        urls = self.override_urls() + self.base_urls() + self.nested_urls()
        return patterns('', *urls) + self.detail_actions_urlpatterns()

    def get_multiple(self, request, **kwargs):
        """
        Same as the original ``get_multiple`` but supports using the custom
        ``url_id_attribute`` instead of the pk of the objects.
        """
        self.method_check(request, allowed=['get'])
        self.is_authenticated(request)
        self.throttle_check(request)

        # Rip apart the list then iterate.
        list_name = '%s_list' % self._meta.url_id_attribute
        obj_attributes = kwargs.get(list_name, '').split(';')
        objects = []
        not_found = []

        for att_value in obj_attributes:
            try:
                # Get the object by our attribute
                obj = self.obj_get(request,
                                   **{self._meta.url_id_attribute: att_value})
                bundle = self.build_bundle(obj=obj, request=request)
                bundle = self.full_dehydrate(bundle)
                objects.append(bundle)
            except ObjectDoesNotExist:
                not_found.append(att_value)

        object_list = {'objects': objects}

        if len(not_found):
            object_list['not_found'] = not_found

        self.log_throttled_access(request)
        return self.create_response(request, object_list)

    def get_resource_uri(self, bundle_or_obj):
        """
        Same as the original ``get_resource_uri`` but supports using the custom
        ``url_id_attribute`` instead of the pk of the objects.
        """
        kwargs = {'resource_name': self._meta.resource_name}

        # If url_id_attribute was not declared it has already been set to 'pk'
        # by the metaclass.
        id_attr_name = self._meta.url_id_attribute

        if isinstance(bundle_or_obj, Bundle):
            kwargs[id_attr_name] = getattr(bundle_or_obj.obj, id_attr_name)
        else:
            kwargs[id_attr_name] = getattr(bundle_or_obj, id_attr_name)

        if self._meta.api_name is not None:
            kwargs['api_name'] = self._meta.api_name

        return self._build_reverse_url("api_dispatch_detail", kwargs=kwargs)

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
        try:
            parent_object = self.get_object_list(request).get(**kwargs)

            # If I am not authorized for the parent
            if not self.is_authorized_over_parent(request, parent_object):
                stringified_kwargs = ', '.join(["%s=%s" % (k, v)
                                                for k, v in kwargs.items()])
                raise self._meta.object_class.DoesNotExist("Couldn't find an "
                        "instance of '%s' which matched '%s'." %
                        (self._meta.object_class.__name__, stringified_kwargs))

            return parent_object
        except ObjectDoesNotExist:
            return http.HttpNotFound()
        except MultipleObjectsReturned:
            return http.HttpMultipleChoices("More than one parent resource is "
                                            "found at this URI.")

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

    def obj_get(self, request=None, **kwargs):
        """
        Same as the original ``obj_get`` but knows when it is being called to
        get an object from a nested resource uri.

        Performs authorization checks in every case.
        """
        try:
            nested_name = kwargs.pop('nested_name', None)
            parent_resource = kwargs.pop('parent_resource', None)
            parent_object = kwargs.pop('parent_object', None)

            base_object_list = self.get_object_list(request).filter(**kwargs)

            if nested_name is not None:
                # TODO: throw exception if parent_resource or parent_object are
                #       None
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

        kwargs.pop(self._meta.url_id_attribute)

        # TODO: comment further to make sense of this block
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

        # The nested resource needs to get the api_name from its parent because
        # it is possible that the resource being used as nested is not
        # registered in the API (ie. it can only be used as nested)
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

