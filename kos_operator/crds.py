import abc
import logging
import six

try:
    from functools32 import lru_cache
except ImportError: 
    from functools import lru_cache

from kubernetes import client

from keystoneauth1 import session
from keystoneauth1.identity import v3
from openstack import connection

from .templates import CRD_LOADER
from .templates import env

LOG = logging.getLogger(__name__)

class _OSCInstance(object):
    session=None
    region_name=None
    _region_name=None
    endpoint_type='public'
    interface='public'
    insecure=False
    ca_cert=None
    _api_version={
        'baremetal': '1.46'
    }

    def __init__(self, session):
        super(_OSCInstance, self).__init__()
        self.session = session

    def get_endpoint_for_service_type(self, *args, **kwargs):
        return None


@lru_cache()
def _get_session(url, project, domain, user, password):
    auth = v3.Password(
        auth_url=url,
        project_name=project,
        project_domain_name=domain,
        username=user,
        user_domain_name=domain,
        password=password,
    )
          
    return session.Session(auth=auth)


@lru_cache()
def _get_connection(url, project, domain, user, password):
    return connection.Connection(
        auth_url=url,
        project_name=project,
        project_domain_name=domain,
        username=user,
        user_domain_name=domain,
        password=password,
    )


@six.add_metaclass(abc.ABCMeta)
class CustomResourceDefinitionBase(object):
    _crd = None
    _resource_version = 0

    def __init__(self, options):
        self.requirements = []
        self.options = options

    @classmethod
    def poll(cls, options):
        if not cls._crd:
            cls._create_custom_resource_definitions()

        api = client.CustomObjectsApi()
        group = cls._crd.spec['group']
        plural = cls._crd.spec['names']['plural']
        kind = cls._crd.spec['names']['kind']
        version = cls._crd.spec['version']
        kwargs = {
            "watch": False
        }
        if cls._resource_version:
            kwargs['resource_version'] = cls._resource_version
        resp = api.list_cluster_custom_object(
            group, version, plural, **kwargs)
        for item in resp['items']:
            metadata = item.get('metadata', {})
            namespace = metadata.get('namespace', 'missing namespace')
            name = metadata.get('name', 'missing name')
            try:
                obj = cls(options)
                obj.requirements = [
                    (r.get('kind', 'KosQuery'),
                     r.get('namespace', namespace),
                     r['name'])
                    for r in item.get('requirements', [])]
                obj._process_crd_item(item)
                yield (kind, namespace, name), obj
            except KeyError as e:
                LOG.error("Failed for %s/%s due to missing key %s",
                            namespace,
                            name,
                            e)
            except ValueError as e:
                LOG.error("Failed for %s/%s due to parsing error %s",
                            namespace,
                            name,
                            e)
    
    def execute(self, state):
        pass

    @abc.abstractmethod
    def _process_crd_item(self, item):
        pass

    @classmethod
    @abc.abstractmethod
    def _custom_resource_definition(cls):
        pass

    @classmethod
    def _create_custom_resource_definitions(cls):
        if cls._crd:
            return

        api = client.ApiextensionsV1beta1Api()
        cls._crd = cls._custom_resource_definition()
        if cls._crd:
            try:
                api.create_custom_resource_definition(cls._crd)
            except (client.rest.ApiException, ValueError):
                # ValueError is raised by our old api version
                pass

class OpenstackSeed(CustomResourceDefinitionBase):
    API_GROUP = 'openstack.stable.sap.cc'
    _crd = None
    _resource_version = 0

    @classmethod
    def _create_custom_resource_definitions(cls):
        # Do not create it, expect it to be created the 
        # original operator
        cls._crd = \
            cls._custom_resource_definition()

    @classmethod
    def _custom_resource_definition(cls):
        singular = 'openstackseed'
        plural = singular + 's'
        name = '{}.{}'.format(plural, cls.API_GROUP)
        return client.V1beta1CustomResourceDefinition(
            metadata={
                'name': name,
            },
            spec={
                'group': cls.API_GROUP,
                'version': 'v1',
                'versions': [{'name': 'v1',
                              'served': True,
                              'storage': True}],
                'scope': 'Namespaced',
                'names': {
                    'singular': singular,
                    'plural': plural,
                    'kind': 'OpenstackSeed',
                    'listKind': 'OpenstackSeedList',
                }
            }
        )
    
    def _process_crd_item(self, item):
        self.options[item['metadata']['name']] = item['spec']

class TemplateBase(CustomResourceDefinitionBase):
    def __init__(self, options):
        super(TemplateBase, self).__init__(options)
        self.mapping = CRD_LOADER.mapping
        self.path = None

    def _process_crd_item(self, item):
        version = item['metadata']['resourceVersion']
        name = item['metadata']['name']
        # This, however, does seem to work
        # self.resource_version = max(
        #    version,
        #    self.resource_version)
        scope = item['metadata'].get('scope') or ''
        namespace = item['metadata']['namespace']
        jinja2_options = item['metadata'].get('jinja2_options', {})

        template = item['template']
        self.template_name = '/'.join([scope,namespace,name]) + '.yaml.j2'
        self.mapping[self.template_name] = (version, template, jinja2_options)
    
    def execute(self, state, options=None):
        if not self.template_name:
            return
        options = options or self.options
        template = env.get_template(self.template_name)
        result = template.render(options)
        state.add(result)

class KosQuery(CustomResourceDefinitionBase):
    API_GROUP = 'kos-operator.stable.sap.cc'
    _crd = None
    _resource_version = 0

    @classmethod
    def _custom_resource_definition(cls):
        singular = 'kos-query'
        plural = 'kos-queries'
        name = '{}.{}'.format(plural, cls.API_GROUP)
        return client.V1beta1CustomResourceDefinition(
            metadata={
                'name': name,
            },
            spec={
                'group': cls.API_GROUP,
                'version': 'v1',
                'versions': [{'name': 'v1',
                              'served': True,
                              'storage': True}],
                'scope': 'Namespaced',
                'names': {
                    'singular': singular,
                    'plural': plural,
                    'kind': 'KosQuery',
                    'shortNames': ['kq'],
                }
            }
        )

    def _process_crd_item(self, item):
        super(KosQuery, self)._process_crd_item(item)
        self.commands = item['commands']
        self.user, project = item['context'].split('@', 1)
        self.domain, self.project = project.split('/', 1)
        self.password = self._get_user_password()
        _, dns_domain = self.options['domain'].split('.', 1)
        url = 'https://identity-3.' + dns_domain
        self.connection = _get_connection(
            url,
            self.project,
            self.domain,
            self.user,
            self.password
        )

        if not self.connection:
            LOG.warning("Failed to get connection to %s", url)
            _get_connection.cache_clear()

    def _get_user_password(self):
        for k in six.itervalues(self.options):
            if isinstance(k, dict) and 'domains' in k:
                domains = k['domains']
                for domain in domains:
                    if domain.get('name') != self.domain:
                        continue
                    users = domain.get('users', [])
                    for user in users:
                        if user.get('name') == self.user:
                            if user.get('password'):
                                return user.get('password')
        
        LOG.warning("Could not find password for user %s in domain %s", self.user, self.domain)

    def execute(self, state):
        if not self.connection:
            return
        options = self.options.copy()
        for key, command in six.iteritems(self.commands):
            value = eval(command, {'os': self.connection})
            options[key] = value
        

class KosTemplate(TemplateBase):
    API_GROUP = 'kos-operator.stable.sap.cc'
    _crd = None
    _resource_version = 0

    @classmethod
    def _custom_resource_definition(cls):
        singular = 'kos-template'
        plural = singular + 's'
        name = '{}.{}'.format(plural, cls.API_GROUP)
        return client.V1beta1CustomResourceDefinition(
            metadata={
                'name': name,
            },
            spec={
                'group': cls.API_GROUP,
                'version': 'v1',
                'versions': [{'name': 'v1',
                              'served': True,
                              'storage': True}],
                'scope': 'Namespaced',
                'names': {
                    'singular': singular,
                    'plural': plural,
                    'kind': 'KosTemplate',
                    'shortNames': ['kt'],
                }
            }
        )

    def _process_crd_item(self, item):
        super(KosTemplate, self)._process_crd_item(item)

    def execute(self, state):
        options = self.options.copy()
        super(KosTemplate, self).execute(state, options)

CRDS = [
    OpenstackSeed,
    KosQuery,
    KosTemplate
]
