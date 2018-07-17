import hashlib
import logging

from jinja2 import BaseLoader, ChoiceLoader, FileSystemLoader, Environment, \
    PackageLoader, contextfilter, TemplateNotFound
from kubernetes import client

from masterpassword import MasterPassword

LOG = logging.getLogger(__name__)


def _quote(value):
    return '"{}"'.format(_ini_escape(value).replace('"', '\\"'))


def _ini_escape(value):
    return str(value).replace('$', '$$')


@contextfilter
def _derive_password(ctx, username=None, host=None):
    username = username or ctx['username']
    host = host or ctx['host']
    mpw = MasterPassword(name=username, password=ctx['master_password'])
    password = mpw.derive('long', host).replace("/", "")

    if host.startswith('vc-'):
        return password.replace("/", "")

    return password


def _sha256sum(data):
    sha1 = hashlib.new('sha256')
    sha1.update(data)
    return sha1.hexdigest()


@contextfilter
def _render(ctx, template_name):
    template = ctx.environment.get_template(template_name)
    return template.render(ctx)


class ConfigMapLoader(BaseLoader):
    def __init__(self):
        self.mapping = {}
        self.resource_version = None

    def get_source(self, environment, template):
        if template in self.mapping:
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
        except client.rest.ApiException as e:
            pass


class CustomResourceDefinitionLoader(BaseLoader):
    API_GROUP = 'vcenter-operator.stable.sap.cc'

    def __init__(self):
        self.mapping = {}
        self._crd = None
        self.resource_version = 0

    def get_source(self, environment, template):
        if template in self.mapping:
            source = self.mapping[template]
            return source, None, lambda: source == self.mapping.get(template)
        raise TemplateNotFound(template)

    def list_templates(self):
        self.poll_crds()
        return sorted(self.mapping)

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
        resp = api.list_cluster_custom_object(
            group, version, plural, **kwargs)
        # Doesn't work
        # self.resource_version = resp['metadata']['resourceVersion']
        for item in resp['items']:
            try:
                name = item['metadata']['name']
                # This, however, does seem to work
                # self.resource_version = max(
                #    item['metadata']['resourceVersion'],
                #    self.resource_version)
                scope = 'vcenter_' + item['metadata']['scope']
                namespace = item['metadata']['namespace']
                template = item['template']
                path = '/'.join([scope,namespace,name]) + '.yaml.j2'
                mapping[path] = template
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
        self._crd = CustomResourceDefinitionLoader._custom_resource_definition()
        try:
            response = api.create_custom_resource_definition(self._crd)
        except client.rest.ApiException as e:
            pass


env = Environment(
    loader=ChoiceLoader([
        CustomResourceDefinitionLoader(),
        ConfigMapLoader(),
        FileSystemLoader('/var/lib/kolla/config_files', followlinks=True),
        PackageLoader('vcenter_operator', 'templates')]))

env.filters['ini_escape'] = _ini_escape
env.filters['quote'] = _quote
env.filters['derive_password'] = _derive_password
env.filters['sha256sum'] = _sha256sum
env.filters['render'] = _render
