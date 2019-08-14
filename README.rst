KOS Operator
============

The KOS Operator configures kubernetes (K) based on the results of openstack (OS) api calls

Configuration
-------------
The operator relies on ``OpenstackSeeds`` from the openstack-seeder_, which are queried first.
So, their information is available for subsequent resources.
They are followed by ``KosQueries``, which can use the credentials in the ``OpenstackSeeds`` to query openstack apis,
and store the results in variables, which are then available to all ``KosTemplates`` resources.

Custom Resources
----------------

KosQuery
^^^^^^^^
Queries can be issued by the resource definition ``KosQuery``.

Let's have a look at the following query::

    apiVersion: kos-operator.stable.sap.cc/v1
    kind: KosQuery
    metadata:
        name: baremetal-nodes
        namespace: monsoon3
    context: ironic@Default/service
    requirements:
    - name: ironic-seed
      kind: OpenstackSeed
    python: |
        nodes = [node for node in os.baremetal.nodes()]


context
    With the ``context`` attribute one specifies in which context the API request should be issued.
    The format is ``<user name>@<domain name>/<project name>``
    The credentials are taken form the OpenstackSeeds for the openstack-seeder_
    In the example, it would be the ironic service user in the Default domain and service project.

requirements
    For getting the password, we require the ``OpenstackSeed`` named ``ironic-seed``, we need to specify it
    by name and type.
    The spec-contents of the seed will be available under the name of the seed in the dictionary ``seeds``

python
    The python code will be executed, and the local variables will be available to any template (or query), which requires it.
    
    Currently, you can query openstack with the openstacksdk_ connection under the name ``os``.
    A conversion to a list might be sensible to ensure that we have actual objects instead of an iterator, which can only be iterated over once

    Under ``examples/test.py`` you'll find a python script, which provides you a template to test the code outside of the scope of the operator.

    Other modules available are requests_ (as ``requests``), json_  (as ``json``) and kubernetes_ as ``k8s``.

KosTemplate
^^^^^^^^^^^^^^^^^^

A template can (currently) use any variable defined by any ``KosQuery``::

    apiVersion: kos-operator.stable.sap.cc/v1
    kind: KosTemplate
    metadata:
        name: baremetal-configmap
        namespace: monsoon3
    requirements:
    - name: baremetal-blocks
    template: |
        apiVersion: v1
        kind: ConfigMap
        metadata:
            name: test
        data:
            a: {{ blocks | map('string') | join(',') | quote }}

requirements
    We need some data, reasonably from a ``KosQuery`` to render a template from.
    By default, the kind ``KosQuery`` is assumed.
    To ensure some order, you could also specify a ``KosTemplate`` as a requirement.

template
    The template is a jinja2 template, and all standard filters are available.
    If you want generate a ``KosTemplate`` resource and are bothered by having to quote the variable-start- and end quotes all the time,
    you can configure jinja2 to use different ones by adding to the metadata a map named ``jinja2_options``,
    setting ``variable_start_string``, ``variable_end_string`` (e.g. to ``{=`` and ``=}``).
    Any option here will be passed for the jinja2 interpreter (see jinja2_options_ for more).

.. _openstack-seeder: https://github.com/sapcc/kubernetes-operators/tree/master/openstack-seeder
.. _openstacksdk: https://github.com/openstack/openstacksdk
.. _jinja2_options: http://jinja.pocoo.org/docs/2.10/api/#jinja2.Environment
.. _requests: http://docs.python-requests.org/en/master/
.. _json: https://docs.python.org/2/library/json.html
.. _kubernetes: https://github.com/kubernetes-client/python
