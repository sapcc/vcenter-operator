import base64
import hashlib
import logging

import urllib3.exceptions
from jinja2 import BaseLoader, ChoiceLoader, Environment, TemplateNotFound, pass_context
from kubernetes import client
from masterpassword.masterpassword import MasterPassword

LOG = logging.getLogger(__name__)


class TemplateLoadingError(Exception):
    pass


class CustomResourceDefinitionLoadingError(TemplateLoadingError):
    pass


class ConfigMapLoadingError(TemplateLoadingError):
    pass

class VCenterServiceUserCRDUsernameTemplateDuplicateError(Exception):
    """Exception to skip SSO connection attempts"""
    pass


def _ini_quote(value):
    return '"{}"'.format(_ini_escape(value).replace('"', '\\"'))


def _ini_escape(value):
    return str(value).replace('$', '$$')


@pass_context
def _derive_password(ctx, username=None, host=None):
    username = username or ctx['username']
    host = host or ctx['host']
    mpw = MasterPassword(name=username, password=ctx['master_password'])
    password = mpw.derive('long', host)

    return password


def _sha256sum(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    sha1 = hashlib.new('sha256')
    sha1.update(data)
    return sha1.hexdigest()


@pass_context
def _render(ctx, template_name):
    template = ctx.environment.get_template(template_name)
    return template.render(ctx)


@pass_context
def _get_context(ctx):
    return ctx


def _b64enc(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.b64encode(data).decode('utf-8')


_SAVED_DEFAULTS = {}


def restore_defaults(env):
    global _SAVED_DEFAULTS
    for k in _SAVED_DEFAULTS:
        setattr(env, k, _SAVED_DEFAULTS[k])
    _SAVED_DEFAULTS.clear()


def store_default(env, k):
    global _SAVED_DEFAULTS
    if k in _SAVED_DEFAULTS:
        return

    _SAVED_DEFAULTS[k] = getattr(env, k)


def _owner_from_obj(item):
    metadata = item["metadata"]
    return {
        "apiVersion": item["apiVersion"],
        "kind": item["kind"],
        "name": metadata["name"],
        "blockOwnerDeletion": False,
        "uid": metadata["uid"],
    }


class PollingLoader(BaseLoader):
    API_GROUP = 'vcenter-operator.stable.sap.cc'

    def __init__(self):
        self.mapping = {}
        self._crd = None

    def poll(self):
        raise NotImplementedError()

    def get_source_owner(self, template_name):
        return None

    def list_templates(self):
        return sorted(self.mapping)

    def get_mapping(self):
        return self.mapping


class VCenterTemplateCRDLoader(PollingLoader):

    def get_source(self, environment, template):
        if template in self.mapping:
            version, source, jinja2_options, owner = self.mapping[template]
            restore_defaults(environment)

            for k in jinja2_options:
                if hasattr(environment, k):
                    store_default(environment, k)
                    setattr(environment, k, jinja2_options[k])

            return source, None, lambda: \
                template in self.mapping and \
                (version, source, jinja2_options, owner) == self.mapping.get(template)
        raise TemplateNotFound(template)

    def get_source_owner(self, template_name):
        if template_name not in self.mapping:
            return None

        _, _, _, owner = self.mapping[template_name]
        return owner

    def _read_options_v1(self, item):
        options = {
            'scope': item['metadata']['scope'],
            'jinja2_options': item['metadata'].get('jinja2_options', {})
        }
        return options

    def _read_options_v2(self, item):
        return item['options']

    def poll(self):
        if not self._crd:
            self._create_custom_resource_definitions()

        api = client.CustomObjectsApi()
        mapping = dict()
        group = self._crd.spec['group']
        plural = self._crd.spec['names']['plural']
        version = self._crd.spec['version']
        try:
            resp = api.list_cluster_custom_object(group, version, plural)
        except (client.rest.ApiException, urllib3.exceptions.MaxRetryError) as e:
            raise CustomResourceDefinitionLoadingError(e)

        # Doesn't work
        # self.resource_version = resp['metadata']['resourceVersion']
        for item in resp['items']:
            try:
                metadata = item['metadata']
                version = metadata['resourceVersion']
                name = metadata['name']
                # This, however, does seem to work
                # self.resource_version = max(
                #    version,
                #    self.resource_version)
                namespace = metadata['namespace']
                if 'options' in item:
                    options = self._read_options_v2(item)
                else:
                    options = self._read_options_v1(item)
                scope = 'vcenter_' + options['scope']
                jinja2_options = options.get('jinja2_options', {})
                template = item['template']
                owner = _owner_from_obj(item)
                path = '/'.join([scope, namespace, name]) + '.yaml.j2'
                mapping[path] = (version, template, jinja2_options, owner)
            except KeyError as e:
                LOG.error("Failed for %s/%s due to missing key %s",
                          namespace,
                          name,
                          e)
        self.mapping = mapping

    @staticmethod
    def _custom_resource_definition():
        singular = 'vcenter-template'
        plural = singular + 's'
        name = f'{plural}.{VCenterTemplateCRDLoader.API_GROUP}'
        return client.V1CustomResourceDefinition(
            metadata={
                'name': name,
            },
            spec={
                'group': VCenterTemplateCRDLoader.API_GROUP,
                'version': 'v1',
                'versions': [{'name': 'v1',
                              'served': True,
                              'storage': True}],
                'scope': 'Namespaced',
                'names': {
                    'singular': singular,
                    'plural': plural,
                    'kind': 'VCenterTemplate',
                    'shortNames': ['vct'],
                }
            }
        )

    def _create_custom_resource_definitions(self):
        if self._crd:
            return

        api = client.ApiextensionsV1Api()
        self._crd = \
            VCenterTemplateCRDLoader._custom_resource_definition()

        try:
            api.create_custom_resource_definition(self._crd)
        except client.rest.ApiException:
            LOG.exception("Failed to create custom resource definition vcenter-template")


class VCenterServiceUserCRDLoader(PollingLoader):

    def load(self):
        try:
            self.poll()
        except CustomResourceDefinitionLoadingError as e:
            LOG.error("Failed to load service-user templates: %s", e)
            return False

        return True

    def poll(self):
        if not self._crd:
            self._create_custom_resource_definitions()

        api = client.CustomObjectsApi()

        mapping = dict()

        group = self._crd.spec["group"]
        plural = self._crd.spec["names"]["plural"]
        version = self._crd.spec["version"]
        try:
            resp = api.list_cluster_custom_object(group, version, plural)
        except (client.rest.ApiException, urllib3.exceptions.MaxRetryError) as e:
            raise CustomResourceDefinitionLoadingError(e)

        for item in resp["items"]:
            # Get service-user template names
            try:
                metadata = item["metadata"]
                version = metadata["resourceVersion"]
                name = metadata["name"]
                namespace = metadata["namespace"]
                service_username_template = item["spec"]["username"]
                self._check_service_username_template_exists(mapping, service_username_template)
                mapping[name] = (version, service_username_template, namespace)
            except KeyError as e:
                LOG.error("Failed for %s/%s due to missing key %s", namespace, name, e)
        self.mapping = mapping

    def _check_service_username_template_exists(self, mapping, service_username_template):
        # Checks if the service_username_template already exists to prevent duplicates and potential conflicts
        # Also checks if the service_username_template is a substring of an existing template to prevent conflicts
        for value in mapping.values():
            if service_username_template == value[1] or value[1].startswith(service_username_template):
                raise VCenterServiceUserCRDUsernameTemplateDuplicateError()

    @staticmethod
    def _custom_resource_definition():
        singular = "vcenter-service-user"
        plural = singular + "s"
        name = f"{plural}.{VCenterServiceUserCRDLoader.API_GROUP}"
        return client.V1CustomResourceDefinition(
            metadata={
                "name": name,
            },
            spec={
                "group": VCenterServiceUserCRDLoader.API_GROUP,
                "version": "v1",
                "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True,
                        "schema": {
                            "openAPIV3Schema": {
                                "type": "object",
                                "properties": {
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "username": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                ],
                "scope": "Namespaced",
                "names": {
                    "singular": singular,
                    "plural": plural,
                    "kind": "VCenterServiceUser",
                    "shortNames": ["vcsu"],
                },
            },
        )

    def _create_custom_resource_definitions(self):
        if self._crd:
            return

        api = client.ApiextensionsV1Api()
        self._crd = VCenterServiceUserCRDLoader._custom_resource_definition()

        try:
            api.create_custom_resource_definition(self._crd)
        except client.rest.ApiException:
            LOG.exception("Failed to create custom resource definition service-user")


class K8sEnvironment(Environment):
    def __init__(self):
        self.loaders = [
            VCenterTemplateCRDLoader(),
        ]
        super().__init__(loader=ChoiceLoader(self.loaders))

    def poll_loaders(self):
        all = True
        for loader in self.loaders:
            try:
                loader.poll()
            except TemplateLoadingError:
                all = False
                LOG.exception("Failed to load templates")
        return all

    def get_source_owner(self, template_name):
        for loader in self.loaders:
            owner = loader.get_source_owner(template_name)
            if owner:
                return owner
        return None

    def get_jinja2_options(self, path):
        for loader in self.loaders:
            if path in loader.mapping:
                return loader.mapping[path][2]


env = K8sEnvironment()
vcenter_service_user_crd_loader = VCenterServiceUserCRDLoader()

env.filters['ini_escape'] = _ini_escape
env.filters['ini_quote'] = _ini_quote
env.filters['quote'] = _ini_quote
env.filters['derive_password'] = _derive_password
env.filters['sha256sum'] = _sha256sum
env.filters['render'] = _render
env.filters['b64enc'] = _b64enc
env.globals['context'] = _get_context
env.globals['callable'] = callable
