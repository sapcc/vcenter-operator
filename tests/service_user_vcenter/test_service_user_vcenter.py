import time
from unittest.mock import MagicMock

import pytest

from vcenter_operator.configurator import Configurator


@pytest.fixture
def configurator():
    """Fixture to create a Configurator instance with mocked dependencies"""
    global_options = {
        "dry_run": False,
    }
    domain = "test_domain"

    configurator = Configurator(domain, global_options)
    configurator.vcenter_sso = MagicMock()
    configurator.vault = MagicMock()
    configurator.vcenter_service_user_tracker = {}
    return configurator


def test_service_user_all_missing(configurator):
    """Test check_service_user_vcenter function with no service-user info in tracker"""

    configurator.vcenter_sso.list_service_users.return_value = ["randmom_user"]
    configurator.vault.get_secret.return_value = {
        "username": "test_service_user_template0001",
        "password": "test_password",
    }
    configurator.vcenter_sso.create_service_user.return_value = None

    configurator._check_service_user_vcenter(
        "test_service_user_template", "test_service", "test_host", "test_path", "1"
    )

    configurator.vcenter_sso.list_service_users.called_once_with("test_host", "test_service_user_template")

    assert "test_host" in configurator.vcenter_service_user_tracker["test_service"]
    assert "1" in configurator.vcenter_service_user_tracker["test_service"]["test_host"]
    assert (
        configurator.vcenter_service_user_tracker["test_service"]["test_host"]["1"]
        < time.time()
    )


def test_service_user_missing_vcenter(configurator):
    """Test check_service_user_vcenter function with service-user missing in tracker"""

    configurator.vcenter_sso.list_service_users.return_value = ["randmom_user"]
    configurator.vault.get_secret.return_value = {
        "username": "test_service_user_template0001",
        "password": "test_password",
    }
    configurator.vcenter_sso.create_service_user.return_value = None

    configurator.vcenter_service_user_tracker = {"test_service": {"test_host": {}}}

    configurator._check_service_user_vcenter(
        "test_service_user_template", "test_service", "test_host", "test_path", "1"
    )

    configurator.vcenter_sso.list_service_users.called_once_with("test_host", "test_service_user_template")

    assert "test_host" in configurator.vcenter_service_user_tracker["test_service"]
    assert "1" in configurator.vcenter_service_user_tracker["test_service"]["test_host"]
    assert (
        configurator.vcenter_service_user_tracker["test_service"]["test_host"]["1"]
        < time.time()
    )


def test_service_user_missing_state(configurator):
    """Test check_service_user_vcenter function with service-user in tracker"""

    configurator.vcenter_sso.list_service_users.return_value = ["test_service_user_template0001"]
    configurator.vault.get_secret.return_value = {
        "username": "test_service_user_template0001",
        "password": "test_password",
    }
    configurator.vcenter_sso.create_service_user.return_value = None

    time_last_seen = time.time()

    configurator.vcenter_service_user_tracker = {}

    configurator._check_service_user_vcenter(
        "test_service_user_template", "test_service", "test_host", "test_path", "1"
    )

    configurator.vcenter_sso.list_service_users.called_once_with("test_host", "test_service_user_template")

    assert "test_host" in configurator.vcenter_service_user_tracker["test_service"]
    assert "1" in configurator.vcenter_service_user_tracker["test_service"]["test_host"]
    assert (
        configurator.vcenter_service_user_tracker["test_service"]["test_host"]["1"]
        > time_last_seen
    )
    assert (
        configurator.vcenter_service_user_tracker["test_service"]["test_host"]["1"]
        < time.time()
    )
