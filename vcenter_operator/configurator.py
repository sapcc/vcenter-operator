import atexit
import base64
import http.client
import json
import logging
import re
import ssl
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from os.path import commonprefix

from kubernetes import client
from kubernetes.client.models import V1ObjectMeta, V1Pod, V1PodList
from masterpassword.masterpassword import MasterPassword
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

import vcenter_operator.vcenter_util as vcu
from vcenter_operator.phelm import DeploymentState, ServiceUserPathNotFoundError
from vcenter_operator.templates import env, vcenter_service_user_crd_loader
from vcenter_operator.vault import Vault, VaultSecretNotReplicatedError, VaultUnavailableError
from vcenter_operator.vcenter_sso import SSOSkippedError, VCenterSSO
from vcenter_operator.nsxt_user_manager import NsxtUserAPIHelper

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
        self.service_users = dict()
        self.last_service_user_check = dict()
        self.vcenter_service_user_tracker = dict()
        self.states = dict()
        self.vault = Vault(dry_run=self.global_options.get('dry_run', 'False') == 'True')
        self.vcenter_sso = VCenterSSO(dry_run=self.global_options.get('dry_run', 'False') == 'True')
        self.global_options['cells'] = set()
        self.global_options['domain'] = domain
        self.max_time_not_seen = 60 * 60 * 24
        self.vault_check_interval = 60 * 60 * 24

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
            host = f"{name}.{self.domain}"
            try:
                self._reconnect_vcenter_if_necessary(host)
            except VcConnectionFailedError:
                LOG.error('Connecting to %s failed.', host)
                continue

        if removed:
            LOG.info(f"Gone vcs {removed}")

    def _connect_vcenter(self, host):
        """Create a connection to host and add it to self.vcenters"""
        if self.global_options.get('manage_service_user_passwords', False):
            username = self.global_options['ad_ttu_username']
            password = self.global_options['ad_ttu_password']
        else:
            username = self.username
            if self.mpw is None:
                raise Exception("MasterPassword not initialized")
            password = self.mpw.derive('long', host)

        if host not in self.vcenters:
            self.vcenters[host] = {
                'username': username,
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
                                                user=username,
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
                # vcenter_name needs to be added for password rotation
                cluster_options.update(
                    availability_zone=availability_zone,
                    vcenter_name=vcenter_options['name']
                )
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
        """Poll the configuration from the secret vcenter-operator"""
        secret = client.CoreV1Api().read_namespaced_secret(namespace=self.namespace, name="vcenter-operator")

        manage_service_user_passwords = b64decode(secret.data.pop('manage_service_user_passwords', "")) == 'true'
        self.global_options.update(manage_service_user_passwords=manage_service_user_passwords)

        if manage_service_user_passwords:
            # The maximum time (in seconds) a service-user was not seen before getting deleted
            max_time_not_seen = b64decode(secret.data.pop('max_time_not_seen', ""))
            if self.max_time_not_seen != max_time_not_seen and max_time_not_seen != "":
                self.max_time_not_seen = int(max_time_not_seen)
            # The interval (in seconds) to check the vault for service-user updates
            vault_check_interval = b64decode(secret.data.pop('vault_check_interval', ""))
            if self.vault_check_interval != vault_check_interval and vault_check_interval != "":
                self.vault_check_interval = int(vault_check_interval)

            password_length = int(b64decode(secret.data.pop('password_length')))
            password_digits = int(b64decode(secret.data.pop('password_digits')))
            password_symbols = int(b64decode(secret.data.pop('password_symbols')))
            if password_length <= 0 or password_digits <= 0 or password_symbols <= 0:
                raise ValueError(
                    "password_length, password_digits and password_symbols must be set with non-zero values")
            password_constraints = {
                "length": password_length,
                "digits": password_digits,
                "symbols": password_symbols,
            }
            if self.vault.password_constraints != password_constraints:
                self.vault.set_password_constraints(password_constraints)

            secret_id = b64decode(secret.data.pop('secret_id', ""))
            role_id = b64decode(secret.data.pop('role_id', ""))
            ad_ttu_username = b64decode(secret.data.pop('ad_ttu_username', ""))
            ad_ttu_password = b64decode(secret.data.pop('ad_ttu_password', ""))
            active_directory = b64decode(secret.data.pop('active_directory', ""))

            vault_url = b64decode(secret.data.pop('vault_url', ""))
            if self.global_options.get('vault_url') != vault_url and vault_url != "":
                self.global_options.update(vault_url=vault_url)
                self.vault.set_vault_url(vault_url)

            mount_point_read = b64decode(secret.data.pop('mount_point_read', ""))
            if self.global_options.get('mount_point_read') != mount_point_read and mount_point_read != "":
                self.global_options.update(mount_point_read=mount_point_read)
                self.vault.set_mount_point_read(mount_point_read)

            mount_point_write = b64decode(secret.data.pop('mount_point_write', ""))
            if self.global_options.get('mount_point_write') != mount_point_write and mount_point_write != "":
                self.global_options.update(mount_point_write=mount_point_write)
                self.vault.set_mount_point_write(mount_point_write)

            approle = {"role_id": role_id, "secret_id": secret_id}
            if self.global_options.get('approle') != approle and role_id != "" and secret_id != "":
                self.global_options.update(approle=approle)
                self.vault.set_approle(approle)

            ad_ttu_username_complete = f"{ad_ttu_username}@{active_directory}"
            if self.global_options.get('ad_ttu_username') != ad_ttu_username_complete or \
                self.global_options.get('ad_ttu_password') != ad_ttu_password:
                self.global_options.update(ad_ttu_username=ad_ttu_username_complete, ad_ttu_password=ad_ttu_password)
                self.vcenter_sso.set_ad_ttu_credentials(ad_ttu_username_complete, ad_ttu_password)

            self.vault.login()

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
        label_selector = 'system=openstack,component=nova,type=nova-cell'

        # We read a list of cell names into a set(). Templates can check if a
        # cell they would belong to exists and use the appropriate config of
        # their service.
        return self._poll_nova_cells_from_configmap(label_selector)

    def _poll_nova_cells_from_configmap(self, label_selector: str) -> bool:
        try:
            configmaps = client.CoreV1Api().list_config_map_for_all_namespaces(label_selector=label_selector)
        except client.ApiException as e:
            LOG.error(f"Failed to retrieve configmaps with labels {label_selector}: {e}")
            return False

        if not configmaps.items:
            return False

        for configmap in configmaps.items:
            try:
                self.global_options['cells'].update(configmap.data['cells'].split(','))
            except KeyError as e:
                LOG.error("Malformed ConfigMap %s/%s: KeyError %s", configmap.metadata.namespace,
                          configmap.metadata.name, e)
                return False

        return True

    def poll(self):
        self.poll_config()
        if not self._poll_nova_cells():
            LOG.warning('Polling cells failed. Discontinuing current configuration run.')
            return

        # If we fail to update the templates, we rather do not continue
        # to avoid rendering only half of the deployment
        if not env.poll_loaders():
            return

        if self.global_options['manage_service_user_passwords']:
            if not vcenter_service_user_crd_loader.load():
                LOG.warning('Polling service user templates failed. Discontinuing current configuration run.')
                return

        for host in self.vcenters:
            try:
                values = self._poll(host)
                self._check_pods_and_update_service_user_tracker()
                self._reconcile_service_users(host)

                state = DeploymentState(dry_run=(self.global_options.get('dry_run', 'False') == 'True'))

                for options in values['clusters'].values():
                    state.render('vcenter_cluster', options, self.service_users, self.vcenter_service_user_tracker)

                for options in values['datacenters'].values():
                    state.render('vcenter_datacenter', options, self.service_users, self.vcenter_service_user_tracker)

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
                LOG.warning("Ignoring disconnected %s for this run.", host)
            except VaultUnavailableError:
                LOG.warning("Ignoring host %s for this run due to Vault being unavailable", host)
            except VaultSecretNotReplicatedError:
                LOG.warning("Ignoring host %s for this run due to Vault not beeing replicated", host)
            except SSOSkippedError:
                LOG.warning("Ignoring host %s for this run due to SSO being unavailable", host)
            except http.client.HTTPException as e:
                LOG.warning("%s: %r", host, e)
            except ServiceUserPathNotFoundError as e:
                LOG.warning("Ignoring host %s for this run due to missing service user path in state: %s", host, e)

    def _reconcile_service_users(self, host):
        """
        Ensures that service-users are consistent across Vault and vCenter for the given host
        This method:
            - Verifies all required service-users exist in Vault, creating or rotating them if necessary
            - Ensures the local state tracks the latest version of each service-user
            - Checks that all required service-users exist in vCenter and creates or deletes them as needed
        """
        if not self.global_options['manage_service_user_passwords']:
            return

        for service, (_, service_username_template, _) in vcenter_service_user_crd_loader.get_mapping().items():
            # host: {name}.{domain}
            vcenter_name = host.split('.')[0]
            path = f"{self.global_options['region']}/vcenter-operator/{service}/{vcenter_name}"

            if path not in self.last_service_user_check:
                self.last_service_user_check[path] = 0

            if self.last_service_user_check[path] + self.vault_check_interval < time.time():
                latest_version = self._check_service_user_vault(path, service_username_template, service)
                self.last_service_user_check[path] = time.time()
            else:
                latest_version = self.service_users[path][-1]

            self._check_service_user_vcenter(service_username_template, service, host, path, latest_version)

    def _check_service_user_vault(self, path, service_username_template, service):
        """Generates ground thruth for service-users and checks for new versions in vault"""
        LOG.debug("Checking service-user under path %s in vault", path)
        metadata_write = self.vault.get_metadata(path, read=False)

        # Create service_user in vault, if not exists
        if not metadata_write:
            LOG.info("Service-user not found for path %s in vault - creating service-user in vault", path)
            latest_version, _, _ = self.vault.create_service_user(service_username_template, path, service)
            self.service_users[path] = [latest_version]
            return latest_version

        metadata_read = self.vault.get_metadata(path, read=True)
        # Check if replicated
        if not metadata_read:
            LOG.info("Service-user in vault is not replicated - triggering replication")
            self.vault.trigger_replicate(path)
            raise VaultSecretNotReplicatedError()

        # Check if metadata is up to date
        versions_read = metadata_read['data']['versions']
        versions_write = metadata_write['data']['versions']
        latest_version_read = max(
            (int(version) for version, meta in versions_read.items() if not meta.get("deletion_time")),
            default=0
        )
        latest_version_write = max(
            (int(version) for version, meta in versions_write.items() if not meta.get("deletion_time")),
            default=0
        )
        if latest_version_write > latest_version_read:
            LOG.warning("Service-user of path %s in vault is not up to date - triggering replication", path)
            self.vault.trigger_replicate(path)
            raise VaultSecretNotReplicatedError()

        latest_version = str(latest_version_read)
        expiry_date = metadata_read['data']['custom_metadata']['expiry_date']
        expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d')

        # Rotate service-user if 90 days before expiry date
        if expiry_date < datetime.now() + timedelta(days=90):
            LOG.info("Service-user in vault is about to expire for path %s", path)
            latest_version, _, _ = self.vault.create_service_user(
                service_username_template, path, service, latest_version
            )
            if self.service_users.get(path):
                self.service_users[path].append(latest_version)
            else:
                self.service_users[path] = [latest_version]
            return latest_version

        # Generating ground truth for service-users
        if path not in self.service_users:
            LOG.info("Generating ground truth for service-user in path %s", path)
            # Could have been rotated during restarts
            latest_version = self.vault.check_and_update_username_if_neccessary(
                path, service, service_username_template)
            self.service_users[path] = [latest_version]
            return latest_version

        # Check if is latest version
        if latest_version != self.service_users[path][-1]:
            LOG.info("New version %s in path %s", latest_version, path)
            latest_version = self.vault.check_and_update_username_if_neccessary(
                path, service, service_username_template)
            self.service_users[path].append(latest_version)
            return latest_version

        return latest_version

    def _check_service_user_vcenter(self, service_username_template, service, host, path, latest_version):
        """Check if service-user in vcenter is up to date"""
        current_username = service_username_template + str(latest_version).zfill(4)

        # Check if vcenter_service_user_tracker has an entry for vcenter and service combination
        if service not in self.vcenter_service_user_tracker:
            self.vcenter_service_user_tracker[service] = dict()

        if host not in self.vcenter_service_user_tracker[service]:
            self.vcenter_service_user_tracker[service][host] = dict()

        service_users_in_vcenter = self.vcenter_sso.list_service_users(host, service_username_template)

        # Check if current_username is in vcenter
        if current_username not in service_users_in_vcenter:
            LOG.info("Creating service-user %s in vcenter", current_username)
            secret = self.vault.get_secret(path)
            if secret["username"] != current_username:
                LOG.warning("Username in vault does not match the current username")
                self.vault.trigger_replicate(path)
                raise VaultSecretNotReplicatedError()

            self.vcenter_sso.create_service_user(host, secret["username"], secret["password"], service)
            self.vcenter_sso.add_user_to_group(host, secret["username"])
            self.vcenter_service_user_tracker[service][host][latest_version] = time.time()

        if not self.vcenter_sso.check_users_in_group(host, current_username):
            LOG.info("Adding service-user %s to Administrators group in vcenter", current_username)
            self.vcenter_sso.add_user_to_group(host, current_username)

        # Check if service-user can be removed
        for service_user in service_users_in_vcenter:
            if not service_user.startswith(service_username_template):
                LOG.debug("Service-user %s does not match service-user template %s - skipping",
                          service_user, service_username_template)
                continue

            version = str(int(service_user.removeprefix(service_username_template)))
            # Recreating the ground truth for service-users
            if version not in self.vcenter_service_user_tracker[service][host].keys():
                self.vcenter_service_user_tracker[service][host][version] = time.time()
                continue

            # Rules:
            # 1. if service-user is the current one, do not delete
            # 2. never delete latest service-user
            # 3. only delete after not seeing pod with version for MAX_TIME_NOT_SEEN
            if service_user == current_username:
                continue

            if len(service_users_in_vcenter) <= 1:
                LOG.debug("Only one service-user in vcenter - nothing to delete")
                return

            if self.vcenter_service_user_tracker[service][host][version] + self.max_time_not_seen < time.time():
                LOG.info("Deleting service-user %s in vcenter %s because it was not seen for %d seconds", service_user,
                          host, self.max_time_not_seen)
                self.vcenter_sso.delete_service_user(host, service_user)
                del self.vcenter_service_user_tracker[service][host][version]

    def _check_pods_and_update_service_user_tracker(self):
        """Check if pods with service-users are still running and update the vcenter_service_user_tracker"""
        if not self.global_options['manage_service_user_passwords']:
            return

        pods: V1PodList = client.CoreV1Api().list_namespaced_pod(
            self.namespace, label_selector="vcenter-operator-secret-version")
        service_users = vcenter_service_user_crd_loader.get_mapping()

        if pods is None or pods.items is None:
            LOG.debug("No pods found - nothing to update")
            return

        for pod in pods.items:
            pod: V1Pod = pod
            metadata: V1ObjectMeta = pod.metadata
            annotations = metadata.annotations or {}
            labels = metadata.labels or {}

            service = annotations.get("uses-service-user")
            vcenter = labels.get("vcenter")
            version = labels.get("vcenter-operator-secret-version")
            if service and vcenter and version:
                if service in service_users:
                    _, service_username_template, _ = service_users[service]
                    service_user = service_username_template + str(version).zfill(4)
                    LOG.debug("Found pod with service-user %s and version %s - updating last seen timestamp",
                               service_user, version)

                    # Check if vcenter_service_user_tracker has an entry for vcenter and service combination
                    if service not in self.vcenter_service_user_tracker:
                        self.vcenter_service_user_tracker[service] = dict()

                    if vcenter not in self.vcenter_service_user_tracker[service]:
                        self.vcenter_service_user_tracker[service][vcenter] = dict()

                    self.vcenter_service_user_tracker[service][vcenter][str(version)] = time.time()

    def _check_nsxt_service_user(self, service_user_prefix, service, bb, path, latest_version, group):
        """Check if service-user is still running"""

        technical_user = "osapinsxt"
        password = ""
        region = "qa-de-1"
        role = "admin"

        current_username = service_user_prefix + str(latest_version).zfill(4)

        nsxt = NsxtUserAPIHelper(technical_user, password, bb, region)
        active_users = nsxt.list_users(prefix=service_user_prefix)

        # Check if vcenter_service_user_tracker has an entry for vcenter and service combination
        if service not in self.vcenter_service_user_tracker:
            self.vcenter_service_user_tracker[service] = dict()

        if bb not in self.vcenter_service_user_tracker[service]:
            self.vcenter_service_user_tracker[service][bb] = dict()

        ## NSXT limits the number of active users to 2
        user_limit_reached = len(active_users) > 1
        ## Create current user in NSXT
        if  current_username not in active_users:
            LOG.info("Creating NSXT service-user %s in NSXT Manager for BB %s", current_username, bb)

            secret = self.vault.get_secret(path)

            if secret['username'] != current_username:
                LOG.warning("NSXT service-user in vault does not match the current username")
                self.vault.trigger_replicate(path)
                raise VaultSecretNotReplicatedError

            if not user_limit_reached:
                LOG.error("NSX-T supports only 2 technical users. Currenlty active uses %s", active_users)
                nsxt.create_service_user(secret['username'], secret['password'])
                nsxt.add_user_to_group(current_username, group)
                ## Remove leading zeros
                self.vcenter_service_user_tracker[service][bb][str(int(latest_version))] = time.time()

        ## User needs the correct role
        if not (nsxt.check_users_in_group(current_username, group)) and not user_limit_reached:
            LOG.info("NSXT service-user %s misses role %s. Adding it", current_username, role)
            nsxt.add_user_to_group(current_username, group)

        ## Check outdated service-user
        for user in active_users:
            if not user.startswith(service_user_prefix):
                LOG.debug("Service-user %s does not match service-user template %s - skipping",
                          user, service_user_prefix)
                continue

            version = str(int(user.removeprefix(service_user_prefix)))

            ## Stale user - remove in a a later iteration
            if version not in self.vcenter_service_user_tracker[service][bb].keys():
                LOG.info("NSXT: Found stale service-user %s in NSXT Manager for BB %s", user, bb)
                self.vcenter_service_user_tracker[service][bb][version] = time.time()
                continue

            ## Do not delete the active user
            if user == current_username:
                continue

            if self.vcenter_service_user_tracker[service][bb][version] + self.max_time_not_seen < time.time():
                LOG.info("NSXT: Deleting service-user %s in NSXT Manager for BB %s because it was reconciled for %d seconds", 
                         user, bb, self.max_time_not_seen)
                nsxt.delete_service_user(user)
                del self.vcenter_service_user_tracker[service][bb][version]
