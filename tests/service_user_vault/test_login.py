import time
from unittest.mock import MagicMock

import pytest

from vcenter_operator.vault import Vault


@pytest.fixture
def vault():
    """Fixture to create a Vault instance with mocked dependencies"""

    vault = Vault(dry_run=False)
    vault.mount_point_read = "test_mount_point_read"
    vault.mount_point_write = "test_mount_point_write"
    vault.vault_url = "http://test_vault_url"
    vault.approle = {"role_id": "test_role_id", "secret_id": "test_secret_id"}
    vault.password_constraints = {
        "length": 20,
        "digits": 1,
        "symbols": 1,
    }
    vault._request_login = MagicMock()

    return vault


def test_login(vault):
    """Test the login for a successful request"""

    vault._request_login.return_value = "test_token", 1000

    vault.login()

    assert vault.token == "test_token"
    # Should just be millis in difference
    assert vault.next_renew < time.time() + 1000 - 300
    assert vault.next_renew > time.time() + 1000 - 301


def test_login_renew_valid(vault):
    """Test the login with valid token and renew time"""
    vault.token = "test_token"
    vault.next_renew = time.time() + 1000
    vault.login()

    vault._request_login.not_called()


def test_login_renew(vault):
    """Test the login with an expired renew time"""
    vault.token = "test_token"
    vault.next_renew = time.time() - 1000
    vault._request_login.return_value = "test_token", 1000

    vault.login()

    vault._request_login.assert_called_once()
    assert vault.token == "test_token"
    assert vault.next_renew < time.time() + 1000 - 300
    assert vault.next_renew > time.time() + 1000 - 301
