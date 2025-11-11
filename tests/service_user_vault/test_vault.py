import pytest
import re

from vcenter_operator.vault import Vault
from unittest import mock
from unittest.mock import call

URL = "http://random.com"
TOKEN = "TOKEN"
APPROLE = "APROLE"
PATH = "service/name"
DEFAULT_WRITE_MOUNT_POINT = "write"
DEFAULT_READ_MOUNT_POINT = "read"

@pytest.fixture
def vault():
    """Fixture to create a Vault instance with mocked dependencies"""
    vault = Vault(dry_run=False)

    vault.set_vault_url(URL)
    vault.set_approle(APPROLE)
    vault.token = TOKEN

    vault.password_constraints = {
        "length": 20,
        "digits": 1,
        "symbols": 1,
    }

    vault.set_mount_point_read(DEFAULT_READ_MOUNT_POINT)
    vault.set_mount_point_write(DEFAULT_WRITE_MOUNT_POINT)
    return vault


def mocked_requests(*args, **kwargs):
    """ Mock HTTP calls to vault """
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        def raise_for_status(self):

            pass

    if 'metadata' in args[0]:
        return MockResponse({}, 200)
    elif 'data' in args[0]:
        username = kwargs.get("json").get("data").get('username')
        version = re.findall(r"\d+", username)
        if version:
            version = version[0]
        else:
            version = 1

        json_data = {'data':
                         {'version': version}
                     }
        return MockResponse(json_data, 200)
    elif 'gen/replicate' in args[0]:
        return MockResponse({}, 200)
    elif 'gen/password' in args[0]:
        json_data = {'data': {'value': "SecurePW"}}
        return MockResponse(json_data, 200)

    return MockResponse(None, 404)

def test_retrieve_mount_points(vault):
    nsxt_mount_point_write = "new_mount_point"
    vault.set_mount_point_write(nsxt_mount_point_write, service="test_service")

    assert DEFAULT_READ_MOUNT_POINT == vault.get_mountpoint(read=True)
    assert DEFAULT_WRITE_MOUNT_POINT == vault.get_mountpoint(read=False)
    assert DEFAULT_WRITE_MOUNT_POINT == vault.get_mountpoint(read=False, service="does-not-exist")
    assert nsxt_mount_point_write == vault.get_mountpoint(read=False,service="test_service")
 
 
def test_store_service_user_credentials(vault):
    username = "test_username"
    password = "securePW"
    custom_mount_point = "custom_mount_point"


    vault.set_mount_point_write(custom_mount_point, service="test_service")
    with mock.patch('requests.post', side_effect=mocked_requests) as mock_post:
        vault.store_service_user_credentials(username, password, PATH, "test_service")

        expected_call = call(f'{URL}/v1/{custom_mount_point}/data/{PATH}',
            json={'data': {'username': username, 'password': password}},
            headers={'X-Vault-Token': TOKEN})

        assert expected_call in mock_post.call_args_list


def test_trigger_replicate(vault):

    # Default service
    with mock.patch('requests.post', side_effect=mocked_requests) as mock_post:
        vault.trigger_replicate(PATH)

        expected_call = call(f'{URL}/v1/gen/replicate',
                         json={'mount': DEFAULT_WRITE_MOUNT_POINT, 'path': PATH},
                         headers={'X-Vault-Token': TOKEN})

        assert expected_call in mock_post.call_args_list

    with mock.patch('requests.post', side_effect=mocked_requests) as mock_post:
        custom_mount_point_write = "custom_write"
        service = "test_service"
        vault.set_mount_point_write(custom_mount_point_write, service=service)
        vault.trigger_replicate(PATH, service=service)
        expected_call = call(f'{URL}/v1/gen/replicate',
                             json={'mount': custom_mount_point_write, 'path': PATH},
                             headers={'X-Vault-Token': TOKEN})

        assert expected_call in mock_post.call_args_list

def test_create_service_user(vault):
    username = "test_username"
    custom_mount_point = "custom_mount_point"

    vault.set_mount_point_write(custom_mount_point)
    service = "test_service"

    with mock.patch('requests.post', side_effect=mocked_requests):
        with mock.patch('requests.put', side_effect=mocked_requests):
            version, user, password = vault.create_service_user(username, PATH, service)
            assert version == "0001"
            assert user == f"{username}0001"
