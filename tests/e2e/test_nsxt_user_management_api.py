import os
import logging
import pytest

from unittest.mock import MagicMock

from vcenter_operator.configurator import Configurator
from vcenter_operator.nsxt_user_manager import NsxtUserAPIHelper, ObjectAlreadyExistsException, ObjectDoesNotExistException

LOG = logging.getLogger(__name__)

USERNAME = "guestuser1"
NEW_PASSWORD = "GuestUser123!!"
USERGROUP = "auditor"


@pytest.fixture
def user_api():
    user = os.getenv('NSXT_USER')
    password = os.getenv('NSXT_PW')
    bb = os.getenv('NSXT_BB')
    region = os.getenv('NSXT_REGION')
    LOG.info(f"connecting to {bb} in region {region} with {user}")

    return NsxtUserAPIHelper(user, password, bb, region)


@pytest.fixture
def delete_user(user_api):
    def delete(user_api):
        try:
            user_api.delete_service_user(USERNAME)
        except Exception as e:
            LOG.error("Failed to delete user %s" % e)
    return delete


@pytest.fixture
def configurator():
    """Fixture to create a Configurator instance with mocked dependencies"""
    global_options = {
        "dry_run": False,
    }
    domain = "test_domain"

    configurator = Configurator(domain, global_options)
    configurator.vault = MagicMock()
    configurator.vcenter_service_user_tracker = {}
    return configurator


def test_create_user_with_mapping(user_api, delete_user):
    delete_user(user_api)
    user_api.create_service_user(USERNAME, NEW_PASSWORD)
    status = user_api.add_user_to_group(USERNAME, USERGROUP)
    assert status


def test_duplicate_user_creation(user_api, delete_user):
    delete_user(user_api)

    user_api.create_service_user(USERNAME, NEW_PASSWORD)

    with pytest.raises(ObjectAlreadyExistsException) as excinfo:
        user_api.create_service_user(USERNAME, NEW_PASSWORD)
    assert str(excinfo.value) == "Object already exists"


def test_group_not_present(user_api):
    with pytest.raises(ObjectDoesNotExistException) as excinfo:
        user_api.add_user_to_group(USERNAME, "NOT_PRESENT")

    assert str(excinfo.value) == "Object does not exist."

def test_list_users(user_api):
    users = user_api.list_users(prefix="admin")
    assert 1 == len(users)

def test_check_nst_service_user(delete_user, user_api, configurator):
    user = os.getenv('NSXT_USER')
    password = os.getenv('NSXT_PW')
    bb = os.getenv('NSXT_BB')
    region = os.getenv('NSXT_REGION')
    LOG.info(f"connecting to {bb} in region {region} with {user}")

    user_prefix = "rotationtest"
    latest_version = "3"
    path = "random/region/stuff"
    # must be nsxt
    service = "nsxt"

    configurator.vault.get_secret.return_value = {
        "username": f"{user_prefix}{latest_version.zfill(4)}",
        "password": NEW_PASSWORD,
    }

    management_user = {
        "username": user,
        "password": password
    }

    configurator._check_nsxt_service_user(user_prefix, service, region, bb, path,
                                          latest_version, management_user, USERGROUP)
