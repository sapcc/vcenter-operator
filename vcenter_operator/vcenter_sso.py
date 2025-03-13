import logging
import time

import pyVmomi
from pyVim import sso
from pyvmomi_extended import SSO_VERSION

LOG = logging.getLogger(__name__)


class SSOSkippedError(Exception):
    """Exception to skip SSO connection attempts"""
    pass


class VCenterSSO:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.saml_token = None
        self.sso_admin_instances = dict()
        self.ad_ttu_username = None
        self.ad_ttu_password = None
        self.domain = "vsphere.local"

    def set_ad_ttu_credentials(self, username, password):
        """Set the credentials for the AD TTU user"""
        self.ad_ttu_username = username
        self.ad_ttu_password = password
        # Reset the SSO instances to ensure they are reconnected with the new credentials
        self.sso_admin_instances = dict()

    def _get_api_instance(self, host):
        """Ensure connection to the SSO instance and return the API instance."""
        if host not in self.sso_admin_instances or not self.sso_admin_instances[host]["api"]:
            self.connect(host)
        return self.sso_admin_instances[host]["api"]

    def connect(self, host):
        """Connect to the vCenter SSO instance"""

        sso_admin_instances = self.sso_admin_instances.get(host)
        if sso_admin_instances:
            retries = sso_admin_instances.get("retry", 0)
            if retries > 0:
                # wait a maximum of 10 minutes, a minium of 1
                wait_time = min(retries, 10) * 60
                if time.time() < sso_admin_instances["last_retry"] + wait_time:
                    LOG.debug(
                        "Ignoring ssoadmin reconnection attempt to %s because of incremental backoff (retry %s).",
                        host,
                        retries,
                    )
                    raise SSOSkippedError()

        try:
            auth = sso.SsoAuthenticator(f"https://{host}/sts/STSService/{self.domain}")

            saml_token = auth.get_bearer_saml_assertion(self.ad_ttu_username, self.ad_ttu_password, delegatable=True)

            stub = pyVmomi.SoapStubAdapter(
                host=host,
                port=443,
                version=SSO_VERSION,
                path=f"/sso-adminserver/sdk/{self.domain}",
                samlToken=saml_token,
                poolSize=0,
            )

            session_manager = pyVmomi.sso.SsoSessionManager("ssoSessionManager", stub=stub)
            session_manager.Login()

            # we do not need to send the token anymore - makes for smaller requests
            stub.samlToken = None

            api = pyVmomi.sso.SsoAdminServiceInstance("SsoAdminServiceInstance", stub=stub).SsoAdminServiceInstance()
            self.sso_admin_instances[host] = {"api": api, "retry": 0, "last_retry": time.time()}
        except Exception as e:
            LOG.error("Error connecting to vCenter SSO instance: %s", e)
            if host in self.sso_admin_instances:
                self.sso_admin_instances[host]["retry"] += 1
                self.sso_admin_instances[host]["last_retry"] = time.time()
            else:
                self.sso_admin_instances[host] = {"api": None, "retry": 0, "last_retry": time.time()}
            LOG.debug(
                "Failed to connect to SSO instance %s. Incrementing retry count to %s.",
                host,
                self.sso_admin_instances[host]["retry"],
            )
            raise SSOSkippedError()

    def list_service_users(self, host, search_string, limit=10000):
        """List service-users in the vCenter via SSO instance"""
        api = self._get_api_instance(host)

        try:
            principal_discovery_service = api.principalDiscoveryService
            criteria = pyVmomi.sso.AdminPrincipalDiscoveryServiceSearchCriteria(
                searchString=search_string, domain=self.domain
            )
            users = principal_discovery_service.FindUsers(criteria=criteria, limit=limit)
            user_names = [user.id.name for user in users]
        except Exception as e:
            LOG.error("Error listing service-users for host %s: %s", host, e)
            del self.sso_admin_instances[host]
            raise SSOSkippedError()

        return user_names

    def check_users_in_group(self, host, search_string, limit=10000):
        """Checks if service-user is in the Administrators group in the vCenter via SSO instance"""
        api = self._get_api_instance(host)

        try:
            principal_discovery_service = api.principalDiscoveryService
            criteria = pyVmomi.sso.AdminPrincipalDiscoveryServiceSearchCriteria(
                searchString="Administrators", domain=self.domain
            )
            groups = principal_discovery_service.FindGroups(criteria=criteria, limit=limit)
            for group in groups:
                if group.id.name != "Administrators":
                    continue
                users = principal_discovery_service.FindUsersInGroup(
                    searchString=search_string, groupId=group.id, limit=limit
                )
                for user in users:
                    if user.id.name == search_string:
                        LOG.debug("User %s is in the Administrators group in vCenter %s", search_string, host)
                        return True
                return False
        except Exception as e:
            LOG.error("Error checking service-users in Administrator group: %s", e)
            del self.sso_admin_instances[host]
            raise SSOSkippedError()

    def create_service_user(self, host, username, password, service):
        """Create a service-user in the vCenter via SSO instance"""
        api = self._get_api_instance(host)
        description = f"Service-user for service {service}"

        try:
            principal_management_service = api.principalManagementService
            details = pyVmomi.sso.AdminPersonDetails(description=description)

            if self.dry_run:
                LOG.debug("Dry-run: Would have created service-user in vcenter %s", host)
                return
            resp = principal_management_service.CreateLocalPersonUser(
                userName=username, userDetails=details, password=password
            )
            if resp and resp.name and resp.name != "":
                LOG.info("Successfully created service-user %s in vCenter %s.", resp.name, host)
            else:
                LOG.error("Failed to create service-user %s in vCenter %s.", username, host)
                raise SSOSkippedError()
        except Exception as e:
            LOG.error("Error creating service-user: %s", e)
            del self.sso_admin_instances[host]
            raise SSOSkippedError()

    def add_user_to_group(self, host, username):
        """Add a service-user to the Administrators group in the vCenter via SSO instance"""
        api = self._get_api_instance(host)

        try:
            principal_discovery_service = api.principalDiscoveryService
            criteria = pyVmomi.sso.AdminPrincipalDiscoveryServiceSearchCriteria(
                searchString=username, domain=self.domain
            )
            users = principal_discovery_service.FindUsers(criteria=criteria, limit=1)
            if len(users) != 1:
                LOG.error("User %s not found in vCenter %s", username, host)
                raise SSOSkippedError()
            user = users[0]
            if user.id.name != username:
                LOG.error("Wrong User %s found in vCenter %s - not %s", user.id.name, host, username)
                raise SSOSkippedError()
        except Exception as e:
            LOG.error("Error listing service-user %s for adding to Administrator group: %s", user.id.name, e)
            raise SSOSkippedError()

        try:
            principal_management_service = api.principalManagementService
            if self.dry_run:
                LOG.debug("Dry-run: Would have added service-user %s to group in vcenter", username, host)
                return
            resp = principal_management_service.AddUsersToLocalGroup(userIds=[user.id], groupName="Administrators")
            if len(resp) == 1 and resp[0]:
                LOG.info("Successfully added service-user %s to Administrator group in vCenter %s.", username, host)
            else:
                LOG.error("Failed to add service-user %s to Administrator group in vCenter %s.", username, host)
                raise SSOSkippedError()
        except Exception as e:
            LOG.error("Error adding service-user to Administrator group for user %s: %s", username, e)
            del self.sso_admin_instances[host]
            raise SSOSkippedError()

    def delete_service_user(self, host, username):
        """Delete a service-user in the vCenter via SSO instance"""
        api = self._get_api_instance(host)

        try:
            if self.dry_run:
                LOG.debug("Dry-run: Would have deleted service-user in vcenter %s", host)
                return

            principal_management_service = api.principalManagementService
            principal_management_service.DeleteLocalPrincipal(principalName=username)
            LOG.info("Successfully deleted service-user %s in vCenter %s.", username, host)
        except Exception as e:
            LOG.error("Error deleting service-user: %s", e)
            del self.sso_admin_instances[host]
            raise SSOSkippedError()
