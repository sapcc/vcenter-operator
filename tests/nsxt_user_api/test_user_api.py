import os
import logging
import pytest

from vcenter_operator.nsxt_ss import NsxtUserAPIHelper, ObjectAlreadyExistsException, ObjectDoesNotExistException

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

def test_create_user_with_mapping(user_api, delete_user):
    delete_user(user_api)
    user_api.create_service_user(USERNAME, NEW_PASSWORD)
    status = user_api.add_user_to_group(USERNAME, USERGROUP)
    assert status == True

def test_duplicate_user_creation(user_api, delete_user):
    delete_user(user_api)

    user_api.create_service_user(USERNAME, NEW_PASSWORD)

    with pytest.raises(ObjectAlreadyExistsException) as excinfo:
        user_api.create_service_user(USERNAME, NEW_PASSWORD)
    assert str(excinfo.value) == "Object already exists"

def test_group_not_present(user_api):
    with pytest.raises(ObjectDoesNotExistException) as excinfo:
        user_api.add_user_to_group(USERNAME, "NOT_PRESENT")

    assert str(excinfo.value) == "Object does not exist.".format(USERNAME)
