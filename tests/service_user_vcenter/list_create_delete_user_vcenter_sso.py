import logging
import os
from pyvmomi_extended import extend_pyvmomi

from vcenter_operator.vcenter_sso import VCenterSSO
LOG = logging.getLogger(__name__)

logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)-15s %(process)d %(levelname)s %(name)s %(message)s'
        )

extend_pyvmomi()

# load ad_username from environment
ad_username = os.environ.get("AD_USERNAME")
ad_password = os.environ.get("AD_PASSWORD")
test_user = "m3testuser"
test_user_password = os.environ.get("TEST_USER_PASSWORD")

host = os.environ.get("VCENTER_HOST")

vcenter_sso = VCenterSSO(dry_run=False)

vcenter_sso.set_ad_ttu_credentials(ad_username, ad_password)

vcenter_sso.connect(host)

LOG.info("Listing all users with search_string=m3testuser in host")
users = vcenter_sso.list_service_users(host=host, limit=1000, search_string="m3testuser")
LOG.info("Users: %s", users)

LOG.info("Creating a new user %s", test_user)
vcenter_sso.create_service_user(
    host=host,
    username=test_user,
    password=test_user_password,
    service="test_service",
)

LOG.info("Listing all users with search_string=m3testuser in host")
users = vcenter_sso.list_service_users(host=host, limit=1000, search_string="m3testuser")
LOG.info("Users: %s", users)

LOG.info("Deleting user %s", test_user)
vcenter_sso.delete_service_user(host=host, username=test_user)

LOG.info("Listing all users with search_string=m3testuser in host")
users = vcenter_sso.list_service_users(host=host, limit=1000, search_string="m3testuser")
LOG.info("Users: %s", users)
