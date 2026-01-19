import logging
import time
from collections import defaultdict

LOG = logging.getLogger(__name__)


class NSXTCacheError(Exception):
    pass


class NSXTManagementCache:
    management_user_path_template = "{region}/compute/nsxt/nsx-ctl-1-{bb}.cc.{region}.cloud.sap/nsxt-shell"

    def __init__(self, region, vault, cache_lifetime=1800):
        self.region = region
        self.vault = vault
        self.cache_lifetime = cache_lifetime
        self.cache = defaultdict(dict)

    def get_secret(self, bb):
        secret_item = self.cache.get(bb)
        if secret_item is None:
            LOG.debug("Retrieving password for key %s", bb)
            return self.renew_pw(bb)

        if time.time() < secret_item["expiry"]:
            return secret_item

        try:
            LOG.debug("Renewing password for key %s", bb)
            return self.renew_pw(bb)
        except NSXTCacheError as e:
            LOG.error("Returning old, cached version because renewal failed: %s", e)
            return secret_item

    def renew_pw(self, bb):
        management_user_path = self.management_user_path_template.format(region=self.region, bb=bb)
        try:
            vault_secret = self.vault.get_secret(management_user_path)
        except Exception as e:
            raise NSXTCacheError(f"NSXT: Not able to fetch management user"
                                 f"for nsxt shell user {management_user_path}: {e}")
        vault_secret["expiry"] = time.time() + self.cache_lifetime
        self.cache[bb] = vault_secret
        return vault_secret
