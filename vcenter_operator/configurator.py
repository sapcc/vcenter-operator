import atexit
import json
import logging
import re
import ssl
import six

from collections import deque
from contextlib import contextmanager
from keystoneauth1.session import Session
from keystoneauth1.identity.v3 import Password
from keystoneauth1.exceptions.http import HttpError
from os.path import commonprefix
from socket import error as socket_error
from kubernetes import client
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from jinja2.exceptions import TemplateError
from yaml.parser import ParserError

from .masterpassword import MasterPassword
from .phelm import DeploymentState
from .templates import env
from .vcenter_util import *

LOG = logging.getLogger(__name__)


@contextmanager
def filter_spec_context(service_instance,
                        obj_type=vim.ClusterComputeResource,
                        path_set=['name', 'parent',
                                  'datastore', 'network']):
    try:
        view_ref = get_container_view(service_instance, obj_type=[obj_type])
        yield create_filter_spec(view_ref=view_ref,
                                 obj_type=obj_type,
                                 path_set=path_set)
    finally:
        if view_ref:
            view_ref.DestroyView()


class Configurator(object):
    CLUSTER_MATCH = re.compile('^production(bb[1-9][0-9]*)$')
    EPH_MATCH = re.compile('^eph.*$')
    BR_MATCH = re.compile('^br-(.*)$')

    def __init__(self, domain, global_options={}):
        self.global_options = global_options.copy()
        self.password = None
        self.mpw = None
        self.domain = domain
        self.os_session = None
        self.vcenters = dict()
        self.states = deque()
        self.poll_config()
        self.global_options['cells'] = {}
        self.global_options['domain'] = domain

    def __call__(self, added, removed):
        for name in added:
            try:
                host = '{}.{}'.format(name, self.domain)
                if host in self.vcenters:
                    continue

                # Vcenter doesn't accept / in password
                password = self.mpw.derive('long', host).replace("/", "")

                LOG.info("{}".format(host))
                if hasattr(ssl, '_create_unverified_context'):
                    context = ssl._create_unverified_context()

                    service_instance = SmartConnect(host=host,
                                                    user=self.username,
                                                    pwd=password,
                                                    port=443,
                                                    sslContext=context)

                if service_instance:
                    atexit.register(Disconnect, service_instance)

                    self.vcenters[host] = {
                        'service_instance': service_instance,
                        'username': self.username,
                        'password': password,
                        'host': host,
                        'name': name,
                    }

            except vim.fault.InvalidLogin as e:
                LOG.error("%s: %s", host, e.msg)
            except (Exception, socket_error) as e:
                LOG.error("%s: %s", host, e)

        if removed:
            LOG.info("Gone vcs {}".format(removed))

    def _poll(self, host):
        vcenter_options = self.vcenters[host]
        values = {'clusters': {}, 'datacenters': {}}
        service_instance = vcenter_options['service_instance']

        nsx_t_clusters = set()

        with filter_spec_context(service_instance,
                obj_type=vim.HostSystem,
                path_set=['name', 'parent', 'config.network.opaqueSwitch']) as filter_spec:
            for h in collect_properties(service_instance, [filter_spec]):
                if 'config.network.opaqueSwitch' not in h:
                    LOG.debug("Broken ESXi host %s detected in cluster %s",
                              h['name'], h['parent'])
                    continue
                if len(h['config.network.opaqueSwitch']) > 0:
                    LOG.debug("(Possible) NSX-T switch found on %s", h['name'])
                    nsx_t_clusters.add(h['parent'])

        with filter_spec_context(service_instance) as filter_spec:
            availability_zones = set()
            cluster_options = None

            for cluster in collect_properties(service_instance, [filter_spec]):
                cluster_name = cluster['name']
                match = self.CLUSTER_MATCH.match(cluster_name)

                if not match:
                    LOG.debug(
                        "%s: Ignoring cluster %s "
                        "not matching naming scheme", host, cluster_name)
                    continue

                nsx_t_enabled = cluster['obj'] in nsx_t_clusters
                if nsx_t_enabled:
                    LOG.debug('NSX-T enabled for %s', cluster_name)

                parent = cluster['parent']
                availability_zone = parent.parent.name.lower()

                availability_zones.add(availability_zone)
                cluster_options = self.global_options.copy()
                cluster_options.update(vcenter_options)
                cluster_options.pop('service_instance', None)
                cluster_options.update(name=match.group(1).lower(),
                                       cluster_name=cluster_name,
                                       availability_zone=availability_zone,
                                       nsx_t_enabled=nsx_t_enabled)

                if cluster_options.get('pbm_enabled', 'false') != 'true':
                    datastores = cluster['datastore']
                    datastore_names = [datastore.name
                                       for datastore in datastores
                                       if self.EPH_MATCH.match(datastore.name)]
                    eph = commonprefix(datastore_names)
                    cluster_options.update(datastore_regex="^{}.*".format(eph))

                for network in cluster['network']:
                    try:
                        match = self.BR_MATCH.match(network.name)
                        if match:
                            cluster_options['bridge'] = match.group(0).lower()
                            cluster_options['physical'] = match.group(1).lower()
                            break
                    except vim.ManagedObjectNotFound:
                        # sometimes a portgroup might be already deleted when
                        # we try to query its name here
                        continue

                if not 'bridge' in cluster_options and not nsx_t_enabled:
                    LOG.warning("%s: Skipping cluster %s, "
                                "cannot find bridge matching naming scheme",
                                host, cluster_name)
                    continue

                values['clusters'][cluster_name] = cluster_options
                self._add_code('vcenter_cluster', cluster_options)

            for availability_zone in availability_zones:
                cluster_options = self.global_options.copy()
                cluster_options.update(vcenter_options)
                cluster_options.pop('service_instance', None)
                cluster_options.update(availability_zone=availability_zone)
                values['datacenters'][availability_zone] = cluster_options

            if cluster_options:
                self._add_code('vcenter_datacenter', cluster_options)
        return values

    def _add_code(self, scope, options):
        for template_name in env.list_templates(
                filter_func=lambda x: (x.startswith(scope)
                                       and x.endswith('.yaml.j2'))
        ):
            try:
                template = env.get_template(template_name)
                result = template.render(options)
                self.states[-1].add(result)
            except (TemplateError, ParserError):
                LOG.exception("Failed to render %s", template_name)

    @property
    def _client(self):
        return client

    @property
    def username(self):
        return self.global_options['username']

    @property
    def namespace(self):
        return self.global_options['own_namespace']

    def poll_config(self):
        configmap = client.CoreV1Api().read_namespaced_config_map(
            namespace=self.namespace,
            name='vcenter-operator',
            export=True)

        password = configmap.data.pop('password')
        for key, value in configmap.data.items():
            try:
                self.global_options[key] = json.loads(value)
            except ValueError:
                self.global_options[key] = value
        if self.password != password:
            self.global_options.update(master_password=password)
            self.password = password
            self.mpw = MasterPassword(self.username, self.password)
            self.setup_os_session()

    def setup_os_session(self):
        os_username = self.global_options.get('os_username')
        if not os_username:
            return
        os_username += self.global_options.get('user_suffix', '')
        mpw = MasterPassword(os_username, self.password)
        host = "identity-3." + self.domain.split('.', 1)[1]
        password = mpw.derive('long', host)
        auth = Password(
            auth_url='https://' + host + '/v3',
            username=os_username,
            user_domain_name=self.global_options.get('os_user_domain_name'),
            project_name=self.global_options.get('os_project_name'),
            project_domain_name=self.global_options.get('os_project_domain_name'),
            password=password,
        )
        self.os_session = Session(auth=auth)

    def poll_nova(self):
        if not self.os_session:
            return

        try:
            endpoint_filter={'service_type': 'compute', 'interface': 'public'}
            resp = self.os_session.get('/os-cells', endpoint_filter=endpoint_filter)
            for cell in resp.json().get('cellsv2', []):
                self.global_options['cells'][cell['name']] = cell
        except HttpError:
            LOG.error("Failed to get cells")

    def poll(self):
        self.poll_config()
        self.poll_nova()
        self.states.append(DeploymentState(
            namespace=self.global_options['namespace'],
            dry_run=(self.global_options.get('dry_run', 'False') == 'True')))

        hosts = {}
        for host in six.iterkeys(self.vcenters):
            try:
                hosts[host] = self._poll(host)
            except six.moves.http_client.HTTPException as e:
                LOG.warning("%s: %r", host, e)
                continue

        all_values = {'hosts': hosts}
        all_values.update(self.global_options)
        all_values.pop('service_instance', None)
        self._add_code('vcenter_global', all_values)

        if len(self.states) > 1:
            last = self.states.popleft()
            delta = last.delta(self.states[-1])
            delta.apply()
        else:
            self.states[-1].apply()
