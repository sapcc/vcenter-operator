import logging
import string
import time
from datetime import datetime, timedelta
from functools import wraps

import requests

LOG = logging.getLogger(__name__)

EXPIRY_DAYS = 365
RENEW_MARGIN_SECONDS = 5 * 60


class VaultUnavailableError(Exception):
    """Custom exception for Vault unavailability"""
    pass

class VaultSecretNotReplicatedError(Exception):
    """Custom exception for Vault secret not replicated to read mount point"""
    pass


class Vault:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.vault_url = None
        self.mount_point_read = None
        self.mount_point_write = None
        self.token = None
        self.next_renew = None
        self.approle = None
        self.password_constraints = None

    def require_vault_parameters(fn):
        @wraps(fn)
        def wrapped(self, *args, **kwargs):
            """Check if all required parameters are set"""
            if not self.vault_url:
                raise ValueError("Vault URL is not set.")
            if not self.mount_point_read:
                raise ValueError("Mount point read is not set.")
            if not self.mount_point_write:
                raise ValueError("Mount point write is not set.")
            if not self.approle:
                raise ValueError("Approle is not set.")
            if not self.password_constraints:
                raise ValueError("Password constraints are not set.")

            return fn(self, *args, **kwargs)

        return wrapped

    def set_approle(self, approle):
        """Set the approle for vault authentication"""
        self.approle = approle

    def set_vault_url(self, vault_url):
        """Set the vault url for vault instance"""
        self.vault_url = vault_url

    def set_mount_point_read(self, mount_point_read):
        """Set the mount point to read from for vault instance"""
        self.mount_point_read = mount_point_read

    def set_mount_point_write(self, mount_point_write):
        """Set the mount point to read from for vault instance"""
        self.mount_point_write = mount_point_write

    def set_password_constraints(self, password_constraints):
        """Set the password constraints for vault instance"""
        self.password_constraints = password_constraints

    def _get_headers(self):
        """Helper method to generate headers for vault requests"""
        if not self.token:
            raise VaultUnavailableError("Vault token is not available. Please login first.")
        return {"X-Vault-Token": self.token}

    @require_vault_parameters
    def login(self):
        """Login with approle to vault"""

        if self.next_renew and self.next_renew > time.time():
            LOG.debug("Token is still valid")
            return

        token, lease_duration = self._request_login()

        self.token = token

        # Set the next renewal time to 5 minutes before the lease duration expires
        self.next_renew = time.time() + lease_duration - RENEW_MARGIN_SECONDS
        LOG.debug("New token is valid for %s seconds.", lease_duration)

    @require_vault_parameters
    def _request_login(self):
        """Login request to the vault instance"""
        resp = requests.post(f"{self.vault_url}/v1/auth/approle/login", json=self.approle)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        resp.raise_for_status()

        auth_data = resp.json().get("auth", {})
        return auth_data.get("client_token"), auth_data.get("lease_duration")

    @require_vault_parameters
    def get_secret(self, path):
        """Get the secret from vault"""

        headers = self._get_headers()
        resp = requests.get(f"{self.vault_url}/v1/{self.mount_point_read}/data/{path}", headers=headers)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        if resp.status_code == 404:
            LOG.warning("Could not find the secret under path %s in vault", path)
            return None

        resp.raise_for_status()

        return resp.json().get("data", {}).get("data")

    @require_vault_parameters
    def get_metadata(self, path, read=False):
        """Get the metadata of the secret"""

        mount = self.mount_point_read if read else self.mount_point_write
        headers = self._get_headers()
        resp = requests.get(f"{self.vault_url}/v1/{mount}/metadata/{path}", headers=headers)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        if resp.status_code == 404:
            LOG.warning("Could not find the secret under path %s in vault", path)
            return None

        resp.raise_for_status()

        return resp.json()

    @require_vault_parameters
    def create_service_user(self, username_template, path, service, last_version=None):
        """Create the service-user"""

        # Initial username starting with 0001 (version 1)
        # When rotating passwords, username is incremented by 1 for parallel use
        username = (
            username_template + "0001"
            if last_version is None
            else username_template + str(int(last_version) + 1).zfill(4)
        )

        password = self.gen_password()

        if self.dry_run:
            LOG.debug("Dry-run: Would have created service-user")
            return "1", username, password

        version = self.store_service_user_credentials(username, password, path, service)

        self.trigger_replicate(path)

        return version, username, password

    @require_vault_parameters
    def gen_password(self):
        """
        Generate a password with the given constraints.
        - length: total length of the password
        - digits: number of digits
        - symbols: number of symbols
        """
        metadata = {
            "length": self.password_constraints["length"],
            "digits": self.password_constraints["digits"],
            "symbols": self.password_constraints["symbols"],
        }

        headers = self._get_headers()
        resp = requests.put(f"{self.vault_url}/v1/gen/password", json=metadata, headers=headers)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        resp.raise_for_status()

        return resp.json().get("data", {}).get("value")

    def check_password_strength(self, password):
        """
        Check if the password meets the strength requirements.
        - length: total length of the password
        - digits: number of digits
        - symbols: number of symbols
        """
        if len(password) != self.password_constraints["length"]:
            return False
        if sum(c.isdigit() for c in password) < self.password_constraints["digits"]:
            return False
        if sum(c in string.punctuation for c in password) < self.password_constraints["symbols"]:
            return False
        return True

    @require_vault_parameters
    def trigger_replicate(self, path):
        """Trigger the replication of a secret in vault"""
        headers = self._get_headers()
        data = {
            "mount": self.mount_point_write,
            "path": path,
        }
        resp = requests.post(f"{self.vault_url}/v1/gen/replicate", json=data, headers=headers)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        resp.raise_for_status()

    @require_vault_parameters
    def store_service_user_credentials(self, username, password, path, service):
        """Stores the service-user credentials in vault"""

        headers = self._get_headers()
        data = {
            "data": {
                "username": username,
                "password": password,
            }
        }

        if self.dry_run:
            LOG.debug("Dry-run: Would have created service-user")
            return "1"

        resp = requests.post(f"{self.vault_url}/v1/{self.mount_point_write}/data/{path}", json=data, headers=headers)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        resp.raise_for_status()

        version = str(resp.json().get("data", {}).get("version"))

        metadata = {
            "custom_metadata": {
                "accessed_resource": service,
                "application_criticallity": "high",
                "expiry_date": (datetime.now() + timedelta(days=EXPIRY_DAYS)).strftime("%Y-%m-%d"),
                "owner": "vcenter-operator",
                "review_date": datetime.now().strftime("%Y-%m-%d"),
                "support_group": "compute-storage-api",
                "type": "secret",
                "username": username,
                "replica_dest_secrets": f"{self.mount_point_read}, {path}"
            }
        }

        resp = requests.post(
            f"{self.vault_url}/v1/{self.mount_point_write}/metadata/{path}", json=metadata, headers=headers)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        resp.raise_for_status()

        return version

    @require_vault_parameters
    def check_and_update_username_if_neccessary(self, path, service, service_username_template):
        """Check if the username is still valid after rotation and update the username if necessary"""

        service_user_data = self.get_service_user_data(path)

        version = str(service_user_data.get("metadata", {}).get("version"))
        username = service_user_data.get("data", {}).get("username")
        password = service_user_data.get("data", {}).get("password")

        if (
            username.startswith(service_username_template)
            and str(int(username.removeprefix(service_username_template))) == version
            and self.check_password_strength(password)
        ):
            LOG.info("Found valid username and password for service %s", service)
            return version

        username = service_username_template + str(int(version) + 1).zfill(4)
        password = self.gen_password()

        LOG.info("Need to update username and password for service %s", service)

        version = self.store_service_user_credentials(username, password, path, service)
        return version

    @require_vault_parameters
    def get_service_user_data(self, path):
        """Get the service-user data from vault"""

        headers = self._get_headers()
        resp = requests.get(f"{self.vault_url}/v1/{self.mount_point_read}/data/{path}", headers=headers)

        if resp.status_code >= 500:
            raise VaultUnavailableError()

        resp.raise_for_status()

        return resp.json().get("data", {})
