import logging
import time

class VaultCacherError(Exception):
    pass

LOG = logging.getLogger(__name__)

class VaultCacher(dict):
    def __init__(self, caching_time):
        self.caching_time = caching_time

    def __setitem__(self, key, pw, username="harald"):
        now = time.time()
        value = {"time": now, "password": pw, username: username}
        super().__setitem__(key, value)

    def __getitem__(self, key):
        pw  =  self.get(key)
        if pw is None:
            raise KeyError(f"No password for key {key}")

        last_pw_check = pw["time"]

        if last_pw_check + self.caching_time > time.time():
            return self.get(key)["password"]
        else:
            LOG.debug("Password for key %s is up-to-date", key)
            return self.renew_pw(key)

    def renew_pw(self, key):
        pass

class NSXTManagementCache(VaultCacher):
    management_user_path_template = "{}/compute/nsxt/nsx-ctl-1-{}.cc.{}.cloud.sap/nsxt-shell"

    def __init__(self, region, vault, cache_lifetime=1800):
        self.region = region
        self.vault = vault
        super().__init__(cache_lifetime)

    def renew_pw(self, key):
        """Key should be the vault path"""
        management_user_path = self.management_user_path_template.format(self.region, key, self.region)
        try:
            management_user = self.vault.get_secret(management_user_path)
        except Exception:
            msg = f"NSXT: Not able to fetch management user for nsxt shell user {management_user_path}"
            raise VaultCacherError(msg)
        super().__setitem__(key, management_user)
        return management_user
