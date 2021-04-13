import base64
import hashlib
import logging
import urllib3.exceptions

from jinja2 import BaseLoader, ChoiceLoader, Environment, \
    contextfilter, contextfunction, TemplateNotFound
from kubernetes import client

from .masterpassword import MasterPassword

LOG = logging.getLogger(__name__)


class TemplateLoadingFailed(Exception):
    pass


class CustomResourceDefinitionLoadingFailed(TemplateLoadingFailed):
    pass


class ConfigMapLoadingFailed(TemplateLoadingFailed):
    pass


def _ini_quote(value):
    return '"{}"'.format(_ini_escape(value).replace('"', '\\"'))


def _ini_escape(value):
    return str(value).replace('$', '$$')


@contextfilter
def _derive_password(ctx, username=None, host=None):
    username = username or ctx['username']
    host = host or ctx['host']
    mpw = MasterPassword(name=username, password=ctx['master_password'])
    password = mpw.derive('long', host)

    if host.startswith('vc-'):
        return password.replace("/", "")

    return password


def _sha256sum(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    sha1 = hashlib.new('sha256')
    sha1.update(data)
    return sha1.hexdigest()


@contextfilter
def _render(ctx, template_name):
    template = ctx.environment.get_template(template_name)
    return template.render(ctx)


@contextfunction
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


class ConfigMapLoader(BaseLoader):
    def __init__(self):
        self.mapping = {}
        self.resource_version = None

    def get_source(self, environment, template):
        if template in self.mapping:
            restore_defaults(environment)
            source = self.mapping[template]
            return source, None, lambda: source == self.mapping.get(template)
        raise TemplateNotFound(template)

    def list_templates(self):
        self.read_config_map()
        return sorted(self.mapping)

    def read_config_map(self):
        try:
            config = client.CoreV1Api().read_namespaced_config_map(
                namespace='kube-system',
                name='vcenter-operator',
                export=False)

            if self.resource_version == config.metadata.resource_version:
                return

            self.mapping = {}
            for key, value in config.data.items():
                if key.endswith(".j2"):
                    self.mapping[key] = value
        except (client.rest.ApiException, urllib3.exceptions.MaxRetryError) as e:
            raise ConfigMapLoadingFailed(e)


class CustomResourceDefinitionLoader(BaseLoader):
    API_GROUP = 'vcenter-operator.stable.sap.cc'

    def __init__(self):
        self.mapping = {}
        self._crd = None
        self.resource_version = 0

    def get_source(self, environment, template):
        if template in self.mapping:
            version, source, jinja2_options = self.mapping[template]
            restore_defaults(environment)

            for k in jinja2_options:
                if hasattr(environment, k):
                    store_default(environment, k)
                    setattr(environment, k, jinja2_options[k])

            return source, None, lambda: \
                template in self.mapping and \
                (version, source, jinja2_options) == self.mapping.get(template)
        raise TemplateNotFound(template)

    def list_templates(self):
        self.poll_crds()
        return sorted(self.mapping)

    def _read_options_v1(self, item):
        options = {
            'scope': item['metadata']['scope'],
            'jinja2_options': item['metadata'].get('jinja2_options', {})
        }
        return options

    def _read_options_v2(self, item):
        return item['options']

    def poll_crds(self):
        if not self._crd:
            self._create_custom_resource_definitions()

        api = client.CustomObjectsApi()
        mapping = dict()
        group = self._crd.spec['group']
        plural = self._crd.spec['names']['plural']
        version = self._crd.spec['version']
        kwargs = {}
        if self.resource_version:
            kwargs['resource_version'] = self.resource_version
        try:
            resp = api.list_cluster_custom_object(
                group, version, plural, **kwargs)
        except (client.rest.ApiException, urllib3.exceptions.MaxRetryError) as e:
            raise CustomResourceDefinitionLoadingFailed(e)
        # Doesn't work
        # self.resource_version = resp['metadata']['resourceVersion']
        for item in resp['items']:
            try:
                version = item['metadata']['resourceVersion']
                name = item['metadata']['name']
                # This, however, does seem to work
                # self.resource_version = max(
                #    version,
                #    self.resource_version)
                namespace = item['metadata']['namespace']
                if 'options' in item:
                    options = self._read_options_v2(item)
                else:
                    options = self._read_options_v1(item)
                scope = 'vcenter_' + options['scope']
                jinja2_options = options.get('jinja2_options', {})
                template = item['template']
                path = '/'.join([scope, namespace, name]) + '.yaml.j2'
                mapping[path] = (version, template, jinja2_options)
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
        name = '{}.{}'.format(plural, CustomResourceDefinitionLoader.API_GROUP)
        return client.V1beta1CustomResourceDefinition(
            metadata={
                'name': name,
            },
            spec={
                'group': CustomResourceDefinitionLoader.API_GROUP,
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

        api = client.ApiextensionsV1beta1Api()
        self._crd = \
            CustomResourceDefinitionLoader._custom_resource_definition()
        try:
            api.create_custom_resource_definition(self._crd)
        except client.rest.ApiException:
            pass


env = Environment(
    loader=ChoiceLoader([
        CustomResourceDefinitionLoader(),
        ConfigMapLoader(),
    ]))

env.filters['ini_escape'] = _ini_escape
env.filters['ini_quote'] = _ini_quote
env.filters['quote'] = _ini_quote
env.filters['derive_password'] = _derive_password
env.filters['sha256sum'] = _sha256sum
env.filters['render'] = _render
env.filters['b64enc'] = _b64enc
env.globals['context'] = _get_context
env.globals['callable'] = callable
