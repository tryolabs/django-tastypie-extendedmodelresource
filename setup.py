#!/usr/bin/env python
# -*- coding: utf-8 -*-
try:
    from setuptools import setup
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup

VERSION = '0.1'

if __name__ == '__main__':
    setup(
        name = 'django-tastypie-extendedmodelresource',
        version = VERSION,
        description = "An extension of TastyPie's ModelResource to easily support nested resources, and more.",
        long_description = open('README.rst', 'r').read(),
        author = 'Alan Descoins, Martín Santos',
        author_email = 'alan@tryolabs.com, santos@tryolabs.com',
        url = 'https://github.com/tryolabs/django-tastypie-extendedmodelresource',
        keywords = "REST RESTful tastypie django resource nested extension",
        license = 'BSD',
        packages = (
            'extendedmodelresource',
        ),
        classifiers = (
            'Development Status :: 4 - Beta',
            'Environment :: Web Environment',
            'Framework :: Django',
            'Intended Audience :: Developers',
            'License :: OSI Approved :: BSD License',
            'Operating System :: OS Independent',
            'Programming Language :: Python',
            'Topic :: Utilities'
        ),
        zip_safe = False,
        install_requires = (
            'Django>=1.3',
            'django-tastypie>=0.9.11',
        ),
    )
