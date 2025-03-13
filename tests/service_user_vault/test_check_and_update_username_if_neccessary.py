from unittest.mock import MagicMock

import pytest

from vcenter_operator.vault import Vault


@pytest.fixture
def vault():
    """Fixture to create a vault instance with mocked dependencies"""

    vault = Vault(dry_run=False)
    vault.token = "test_token"
    vault.next_renew = 9999999998098098
    vault.mount_point_read = "test_mount_point_read"
    vault.mount_point_write = "test_mount_point_write"
    vault.vault_url = "http://test_vault_url"
    vault.approle = {"role_id": "test_role_id", "secret_id": "test_secret_id"}
    vault.password_constraints = {
        "length": 20,
        "digits": 1,
        "symbols": 1,
    }
    vault.get_service_user_data = MagicMock()
    vault.store_service_user_credentials = MagicMock()
    vault.gen_password = MagicMock()

    return vault


def test_valid_name(vault):
    """Test the check_and_update_username_if_neccessary with a valid username."""

    vault.get_service_user_data.return_value = {
        "data": {
            "username": "test_service_user0003",
            "password": "test#password1Tert23",
        },
        "metadata": {"version": "3"},
    }

    version = vault.check_and_update_username_if_neccessary("test_path", "test_service", "test_service_user")

    assert version == "3"


def test_invalid_name(vault):
    """Test the check_and_update_username_if_neccessary with an invalid username."""

    vault.get_service_user_data.return_value = {
        "data": {
            "username": "test_service_user0003",
            "password": "test_password",
        },
        "metadata": {"version": "4"},
    }

    vault.store_service_user_credentials.return_value = "5"
    vault.gen_password.return_value = "test_p4ssword/"

    version = vault.check_and_update_username_if_neccessary("test_path", "test_service", "test_service_user")


    assert version == "5"
