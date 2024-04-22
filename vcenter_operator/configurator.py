import atexit
import base64
import http.client
import json
import logging
import re
import ssl
import time
from contextlib import contextmanager
from os.path import commonprefix

from keystoneauth1.identity.v3 import Password
from keystoneauth1.session import Session
from kubernetes import client
from masterpassword.masterpassword import MasterPassword
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

import vcenter_operator.vcenter_util as vcu

from .phelm import DeploymentState

LOG = logging.getLogger(__name__)


class VcConnectionFailedError(Exception):
    pass


class VcConnectSkippedError(Exception):
    pass


def b64decode(s):
    """Decode the given string and return str() instead of bytes"""
    return base64.b64decode(s).decode('utf-8')


@contextmanager
def filter_spec_context(service_instance,
                        obj_type=vim.ClusterComputeResource,
                        path_set=['name', 'parent',
                                  'datastore', 'network']):
    view_ref = None
    try:
        view_ref = vcu.get_container_view(service_instance, obj_type=[obj_type])
        yield vcu.create_filter_spec(view_ref=view_ref,
                                     obj_type=obj_type,
                                     path_set=path_set)
    finally:
        if view_ref:
            try:
                view_ref.DestroyView()
            except ConnectionRefusedError:
                # if we cannot re-connect, we cannot destroy ... too bad
                pass


class Configurator:
    CLUSTER_MATCH = re.compile('^productionbb0*([1-9][0-9]*)$')
    EPH_MATCH = re.compile('^eph.*$')
    HAGROUP_MATCH = re.compile('.*_hg(?P<hagroup>[ab])$', re.IGNORECASE)
    BR_MATCH = re.compile('^br-(.*)$')

    def __init__(self, domain, global_options={}):
        self.global_options = global_options.copy()
        self.password = None
        self.mpw = None
        self.domain = domain
        self.vcenters = dict()
        self.states = dict()
        self.poll_config()
        self.global_options['cells'] = set()
        self.global_options['domain'] = domain

        atexit.register(self._disconnect_vcenters)

    def _disconnect_vcenters(self):
        """Disconnect all vcenters we are connected to"""
        for host in self.vcenters:
            service_instance = self.vcenters[host].get('service_instance')
            if not service_instance:
                continue
            try:
                Disconnect(service_instance)
            except Exception:
                # best effort disconnection
                pass

    def __call__(self, added, removed):
        """Add/remove vcenters from our managed list of vcenters"""
        for name in added:
            host = f'{name}.{self.domain}'
            try:
                self._reconnect_vcenter_if_necessary(host)
            except VcConnectionFailedError:
                LOG.error('Connecting to %s failed.', host)
                continue

        if removed:
            LOG.info(f"Gone vcs {removed}")

    def _connect_vcenter(self, host):
        """Create a connection to host and add it to self.vcenters"""
        password = self.mpw.derive('long', host)

        if host not in self.vcenters:
            self.vcenters[host] = {
                'username': self.username,
                'password': password,
                'host': host,
                'name': host.split('.', 1)[0],
                'retries': 0,
                'last_retry_time': time.time()
            }
            vc = self.vcenters[host]
        else:
            vc = self.vcenters[host]
            # remove the service_instance for reconnect so we can easily
            # detect a vcenter we are not connected to
            if 'service_instance' in vc:
                del vc['service_instance']

        retries = vc['retries']
        if retries:
            # wait a maximum of 10 minutes, a minium of 1
            wait_time = min(retries, 10) * 60
            if time.time() < vc['last_retry_time'] + wait_time:
                LOG.debug('Ignoring reconnection attempt to %s because of '
                          'incremental backoff (retry %s).', host, retries)
                raise VcConnectSkippedError()

        try:
            LOG.info(f"Connecting to {host}")

            vc['retries'] += 1
            vc['last_retry_time'] = time.time()

            service_instance = None
            if hasattr(ssl, '_create_unverified_context'):
                context = ssl._create_unverified_context()

                service_instance = SmartConnect(host=host,
                                                user=self.username,
                                                pwd=password,
                                                port=443,
                                                sslContext=context)

            if service_instance:
                vc['service_instance'] = service_instance

        except vim.fault.InvalidLogin as e:
            LOG.error("%s: %s", host, e.msg)
        except (OSError, Exception) as e:
            LOG.error("%s: %s", host, e)

        if vc.get('service_instance') is None:
            raise VcConnectionFailedError()
        vc['retries'] = 0

    def _reconnect_vcenter_if_necessary(self, host):
        """Test a vcenter connection and reconnect if necessary"""
        needs_reconnect = \
            host not in self.vcenters or \
            'service_instance' not in self.vcenters[host]
        if not needs_reconnect:
            try:
                self.vcenters[host]['service_instance'].CurrentTime()
            except Exception as e:
                LOG.info('Trying to reconnect to %s because of %s', host, e)
                needs_reconnect = True

        if needs_reconnect:
            self._connect_vcenter(host)

    def _poll(self, host):
        self._reconnect_vcenter_if_necessary(host)
        vcenter_options = self.vcenters[host]
        values = {'clusters': {}, 'datacenters': {}}
        service_instance = vcenter_options['service_instance']

        with filter_spec_context(service_instance) as filter_spec:
            availability_zones = set()
            cluster_options = None

            for cluster in vcu.collect_properties(service_instance, [filter_spec]):
                cluster_name = cluster['name']
                match = self.CLUSTER_MATCH.match(cluster_name)

                if not match:
                    LOG.debug(
                        "%s: Ignoring cluster %s "
                        "not matching naming scheme", host, cluster_name)
                    continue
                bb_name_no_zeroes = f'bb{match.group(1)}'

                parent = cluster['parent']
                availability_zone = parent.parent.name.lower()

                availability_zones.add(availability_zone)
                cluster_options = self.global_options.copy()
                cluster_options.update(vcenter_options)
                cluster_options.pop('service_instance', None)
                cluster_options.update(name=bb_name_no_zeroes,
                                       cluster_name=cluster_name,
                                       availability_zone=availability_zone,
                                       nsx_t_enabled=True,
                                       vcenter_name=vcenter_options['name'])

                if cluster_options.get('pbm_enabled', 'false') != 'true':
                    datastores = cluster['datastore']
                    datastore_names = [datastore.name
                                       for datastore in datastores
                                       if self.EPH_MATCH.match(datastore.name)]
                    eph = commonprefix(datastore_names)
                    cluster_options.update(datastore_regex=f"^{eph}.*")
                    hagroups = set()
                    for name in datastore_names:
                        m = self.HAGROUP_MATCH.match(name)
                        if not m:
                            continue
                        hagroups.add(m.group('hagroup').lower())
                    if {'a', 'b'}.issubset(hagroups):
                        LOG.debug('ephemeral datastore hagroups enabled for %s', cluster_name)
                        cluster_options.update(datastore_hagroup_regex=self.HAGROUP_MATCH.pattern)

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

                values['clusters'][cluster_name] = cluster_options

            for availability_zone in availability_zones:
                cluster_options = self.global_options.copy()
                cluster_options.update(vcenter_options)
                cluster_options.pop('service_instance', None)
                cluster_options.update(availability_zone=availability_zone)
                values['datacenters'][availability_zone] = cluster_options

        return values

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
        secret = client.CoreV1Api().read_namespaced_secret(
            namespace=self.namespace,
            name='vcenter-operator')

        password = b64decode(secret.data.pop('password'))
        for key, value in secret.data.items():
            value = b64decode(value)
            try:
                self.global_options[key] = json.loads(value)
            except ValueError:
                self.global_options[key] = value
        if self.password != password:
            self.global_options.update(master_password=password)
            self.password = password
            self.mpw = MasterPassword(self.username, self.password)

    def _poll_nova_cells(self):
        """Fetch information about Nova's cells"""
        namespace_nova = self.global_options['namespace']
        label_selector = 'system=openstack,component=nova,type=nova-cell'

        # We read a list of cell names into a set(). Templates can check if a
        # cell they would belong to exists and use the appropriate config of
        # their service.
        return self._poll_nova_cells_from_configmap(namespace_nova, label_selector)

    def _poll_nova_cells_from_configmap(self, namespace: str, label_selector: str) -> bool:
        try:
            configmaps = client.CoreV1Api().list_namespaced_config_map(
                namespace=namespace,
                label_selector=label_selector)
        except client.ApiException as e:
            LOG.error(f"Failed to retrieve configmaps with labels {label_selector} from ns {namespace}: {e}")
            return False

        if not configmaps.items:
            return False

        for configmap in configmaps.items:
            try:
                self.global_options['cells'].update(configmap.data['cells'].split(','))
            except KeyError as e:
                LOG.error("Malformed ConfigMap %s/%: KeyError %s", namespace, configmap.metadata.name, e)
                return False

        return True

    def poll(self):
        self.poll_config()
        if not self._poll_nova_cells():
            LOG.warning('Polling cells failed. Discontinuing current configuration run.')
            return

        # If we fail to update the templates, we rather do not continue
        # to avoid rendering only half of the deployment
        if not DeploymentState.poll_templates():
            return

        for host in self.vcenters:
            try:
                values = self._poll(host)
                state = DeploymentState(
                    namespace=self.global_options['namespace'],
                    dry_run=(self.global_options.get('dry_run', 'False')
                             == 'True'))

                for options in values['clusters'].values():
                    state.render('vcenter_cluster', options)

                for options in values['datacenters'].values():
                    state.render('vcenter_datacenter', options)

                last = self.states.get(host)

                if last:
                    delta = last.delta(state)
                    delta.apply()
                else:
                    state.apply()

                self.states[host] = state
            except VcConnectionFailedError:
                LOG.error(
                    "Reconnecting to %s failed. Ignoring VC for this run.", host
                )
            except VcConnectSkippedError:
                LOG.info("Ignoring disconnected %s for this run.", host)
            except http.client.HTTPException as e:
                LOG.warning("%s: %r", host, e)
