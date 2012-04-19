==========================================
 Django TastyPie's Extended ModelResource
==========================================

The ``ExtendedModelResource`` is an extension for TastyPie's ``ModelResource`` that adds some interesting features:

* Supports easily using resources as *nested* of another resource, with proper authorization checks for each case.
* Supports using a custom identifier attribute for resources in uris (not only the object's pk!)


Requirements
============

Required
--------
* django-tastypie 0.9.11 and its requirements.

Optional
--------
* Django 1.4 for the sample project.


Installation
============

Clone repository and do:

    python setup.py install

Or just do

    pip install django-tastypie-extendedmodelresource

to get the latest version from `pypi <http://pypi.python.org/pypi/django-tastypie-extendedmodelresource>`_.


*Nested* resources
==================

Here we explain what we mean by *nested resources* and what a simple use case would be.

Rationale
---------

Imagine you have a simple application which has users, each of which can write any number of entries. Every entry is associated to a user. For example ::

    from django.contrib.auth.models import User
    from django.db import models


    class Entry(models.Model):
        user = models.ForeignKey(User, related_name='entries')
        # ... more fields

The 'standard' TastyPie models for this would be ::

    from django.contrib.auth.models import User
    from tastypie.resources import ModelResource
    
    from myapp.models import Entry


    class UserResource(ModelResource):
        class Meta:
            queryset = User.objects.all()
            
    class EntryResource(ModelResource):
        class Meta:
            queryset = Entry.objects.all()


This gives you full CRUD ability over users and entries, with uris such as ``/api/user/`` and ``/api/entry/``.

Now imagine you want to be able to easily list all the entries authored by a given user, with a uri such as ``/api/user/<pk>/entries``. Additionally, you would like to be able to POST to this uri and create an entry automatically associated to this user. This is why nested resources are for.

If a resource such as the ``EntryResource`` is to be accessed as ``/api/user/<pk>/<something>`` where ``<something>`` is custom-defined (for example ``entries``), then we say the ``EntryResource`` is being used as **nested** of the ``UserResource``. We also say that ``UserResource`` is the **parent** of ``EntryResource``.

The standard TastyPie's ``ModelResource`` would force you to write a function overriding the urls of the ``UserResource`` and adding a method to handle the entry resource (see `Nested Resources <http://django-tastypie.readthedocs.org/en/latest/cookbook.html#nested-resources>`_). Using ``ExtendedModelResource`` it is as easy as ::

    from django.contrib.auth.models import User
    from tastypie import fields

    from extendedmodelresource import ExtendedModelResource
    from myapp.models import Entry


    class UserResource(ExtendedModelResource):
        class Meta:
            queryset = User.objects.all()

        class Nested:
            entries = fields.ToManyField('api.resources.EntryResource', 'entries')


    class EntryResource(ExtendedModelResource):
        user = fields.ForeignKey(UserResource, 'user')

        class Meta:
            queryset = Entry.objects.all()
            
And that's it!


How authorization is handled
----------------------------
If a resource does not have a nested resource, the authorization is handled the same way as in the standard TastyPie. You define an ``Authorization`` class and associate it to the resource. This class may implement the ``is_authorized`` and ``apply_limits`` methods.

For an ``ExtendedModelResource`` with nesteds, all the authorization when using the nested as such is handled from the authorization class **of the parent resource**. For each resource used as nested, the ``Authorization`` class of the parent can implement two methods:

* ``is_authorized_nested_<attribute>``
* ``apply_limits_nested_<attribute>``

where ``<attribute>`` is the name of the attribute parameter in the ``ApiField`` that declares the resource as nested. These functions work identically to the original ones, except that they also receive a ``parent_object`` parameter which will contain the parent object.

For our users and entries example, an ``Authorization`` can be something like::

    from tastypie.authorization import Authorization
    
    
    class UserResourceAuthorization(Authorization):
        """
        Our Authorization class for UserResource and its nested.
        """
    
        def is_authorized(self, request, object=None):
            # Only 'newton' is authorized to view the users
            if 'newton' in request.user.username:
              return True
    
            return False
    
        def apply_limits(self, request, object_list):
            return object_list.all()
    
        def is_authorized_nested_entries(self, request,
                                         parent_object, object=None):
            # Is request.user authorized to access the EntryResource as
            # nested?
            return True
    
        def apply_limits_nested_entries(self, request, parent_object,
                                       object_list):
            # Advanced filtering.
            # Note that object_list already only contains the objects that
            # are associated to parent_object.
            return object_list.all()

Caveats
-------
* ``ExtendedModelResource`` only supports one level nesting.
* Resources used as nested can also be registered in an **Api** instance, but need not to. That is, there can be resources used **only** as nested and not exposed otherwise in the urls.


Changing object's identifier attribute in urls
==============================================

With TastyPie's ``ModelResource`` you can override a method to change the identifier attribute used for objects in the URLs (see `Using Non-PK Data For Your URLs <http://django-tastypie.readthedocs.org/en/latest/cookbook.html#using-non-pk-data-for-your-urls>`_) ::

    class UserResource(ModelResource):
        class Meta:
            queryset = User.objects.all()

        def override_urls(self):
            return [
                url(r"^(?P<resource_name>%s)/(?P<username>[\w\d_.-]+)/$" % self._meta.resource_name, self.wrap_view('dispatch_detail'), name="api_dispatch_detail"),
            ]

This adds a new URL using ``username`` and ignores the old URL using ``pk`` ::

    ^api/ ^(?P<resource_name>user)/(?P<username>[\w\d_.-]+)/$ [name='api_dispatch_detail']
    ^api/ ^(?P<resource_name>user)/$ [name='api_dispatch_list']
    ^api/ ^(?P<resource_name>user)/schema/$ [name='api_get_schema']
    ^api/ ^(?P<resource_name>user)/set/(?P<pk_list>\w[\w/;-]*)/$ [name='api_get_multiple']
    ^api/ ^(?P<resource_name>user)/(?P<pk>\w[\w/-]*)/$ [name='api_dispatch_detail']

But the old URL is still there, and this can be a bit confusing when you have an error with the URLs.

Using ``ExtendedModelResource`` it is as easy as adding a new entry in the ``Meta`` class ::

    class UserResource(ModelResource):
        class Meta:
            queryset = User.objects.all()
            url_id_attribute = 'username'

And you will get this list of urls ::

    ^api/ ^(?P<resource_name>user)/$ [name='api_dispatch_list']
    ^api/ ^(?P<resource_name>user)/schema/$ [name='api_get_schema']
    ^api/ ^(?P<resource_name>user)/set/(?P<username_list>(\w[\w-]*;?)*)/$ [name='api_get_multiple']
    ^api/ ^(?P<resource_name>user)/(?P<username>\w[\w-]*)/$ [name='api_dispatch_detail']

If you need to change the regular expression used for your identifier attribute in the urls, you can override the method ``get_url_id_attribute_regex`` and return it, like the following example ::

    def get_url_id_attribute_regex(self):
        return r'[aA-zZ][\w-]*'

More information
================

:Date: 04-19-2012
:Version: 0.1
:Authors:
  - Alan Descoins - Tryolabs <alan@tryolabs.com>
  - Martín Santos - Tryolabs <santos@tryolabs.com>

:Website:
  https://github.com/tryolabs/django-tastypie-extendedmodelresource
