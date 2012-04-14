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


*Nested* resources
==================
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

Now imagine you want to be able to easily list all the entries of a given user, with a uri such as ``/api/user/<pk>/entries``. Additionally, you would like to be able to POST to this uri and create an entry associated to this user. This is why nested resources are for.

If a resource such as the ``EntryResource`` is to be accessed as ``/api/user/<pk>/<something>`` where ``<something>`` is defined as you wish (for example ``entries``), then we say the ``EntryResource`` is being used as **nested** to the ``UserResource``.

With the standard TastyPie this would force you to write a function overriding the urls of the ``UserResource``. With ``ExtendedModelResource`` it is as easy as ::

    from django.contrib.auth.models import User
    from tastypie import fields

    from extended_resource import ExtendedModelResource
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


Authorization
-------------
TODO


Changing object's identifier attribute in urls
==============================================
TODO


More information
================

:Date: 04-14-2012
:Version: 1.0
:Authors:
  - Alan Descoins - Tryolabs <alan@tryolabs.com>
  - Martín Santos - Tryolabs <santos@tryolabs.com>

:Website:
  https://github.com/tryolabs/django-tastypie-extendedmodelresource
