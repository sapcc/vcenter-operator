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


def test_service_user_not_deleted_only_user(configurator):
    """
    Test check_service_user_vcenter function if only 1 service-user is active
    User should not be deleted
    """

    configurator.vcenter_sso.list_service_users.return_value = ["test_service_user_template0001"]
    configurator.vault.get_secret.return_value = {
        "username": "test_service_user_template0001",
        "password": "test_password",
    }
    configurator.vcenter_sso.create_service_user.return_value = None
    # Set last time seen to 25 hours ago so it can be deleted
    time_last_seen = time.time() - 60 * 60 * 25
    configurator.vcenter_service_user_tracker = {
        "test_service": {"test_host": {"1": time_last_seen}}
    }

    configurator._check_service_user_vcenter(
        "test_service_user_template", "test_service", "test_host", "test_path", "1"
    )

    configurator.vcenter_sso.list_service_users.called_once_with("test_host", "test_service_user_template", "mpw")

    # Should not get deleted! Only user in vcenter for template
    configurator.vcenter_sso.delete_service_user.not_called()

    assert configurator.vcenter_service_user_tracker == {
        "test_service": {"test_host": {"1": time_last_seen}}
    }


def test_service_user_not_deleted_last_seen(configurator):
    """
    Test check_service_user_vcenter function with a service-user that is not older than 24 hours
    Should not be deleted
    """

    configurator.vcenter_sso.list_service_users.return_value = [
        "test_service_user_template0001",
        "test_service_user_template0002",
    ]
    configurator.vault.get_secret.return_value = {
        "username": "test_service_user_template0002",
        "password": "test_password",
    }
    configurator.vcenter_sso.create_service_user.return_value = None

    time_last_seen = time.time() - 60 * 60 * 10
    configurator.vcenter_service_user_tracker = {
        "test_service": {
            "test_host": {
                "1": time_last_seen,
                "2": time_last_seen,
            }
        }
    }

    configurator._check_service_user_vcenter(
        "test_service_user_template", "test_service", "test_host", "test_path", "2"
    )

    configurator.vcenter_sso.list_service_users.called_once_with("test_host", "test_service_user_template", "mpw")

    # Should not get deleted! Not 24 hours old
    configurator.vcenter_sso.delete_service_user.not_called()

    assert configurator.vcenter_service_user_tracker == {
        "test_service": {
            "test_host": {
                "1": time_last_seen,
                "2": time_last_seen,
            }
        }
    }


def test_service_user_deleted_current(configurator):
    """
    Test check_service_user_vcenter function with 2 service-users
    Service-user 2 should not be deleted although it is older than 24 hours
    because it is the current user
    """

    configurator.vcenter_sso.list_service_users.return_value = [
        "test_service_user_template0001",
        "test_service_user_template0002",
    ]
    configurator.vault.get_secret.return_value = {
        "username": "test_service_user_template0002",
        "password": "test_password",
    }
    configurator.vcenter_sso.create_service_user.return_value = None

    time_last_seen = time.time() - 60 * 60 * 10
    time_last_seen_2 = time.time() - 60 * 60 * 25
    configurator.vcenter_service_user_tracker = {
        "test_service": {
            "test_host": {
                "1": time_last_seen,
                "2": time_last_seen_2,
            }
        }
    }

    configurator._check_service_user_vcenter(
        "test_service_user_template", "test_service", "test_host", "test_path", "2"
    )

    configurator.vcenter_sso.list_service_users.called_once_with("test_host", "test_service_user_template", "mpw")

    # Should not get deleted! Is current user
    configurator.vcenter_sso.delete_service_user.not_called()

    assert configurator.vcenter_service_user_tracker == {
        "test_service": {
            "test_host": {
                "1": time_last_seen,
                "2": time_last_seen_2,
            }
        }
    }


def test_service_user_deleted(configurator):
    """
    Test check_service_user_vcenter function with 2 service-users
    Service-user 1 should be deleted because it is older than 24 hours
    Service-user 2 should not be deleted because it is the current user
    """

    configurator.vcenter_sso.list_service_users.return_value = [
        "test_service_user_template0001",
        "test_service_user_template0002",
    ]
    configurator.vault.get_secret.return_value = {
        "username": "test_service_user_template0002",
        "password": "test_password",
    }
    configurator.vcenter_sso.create_service_user.return_value = None

    time_last_seen = time.time() - 60 * 60 * 10
    configurator.vcenter_service_user_tracker = {
        "test_service": {
            "test_host": {
                "1": time.time() - 60 * 60 * 25,
                "2": time_last_seen,
            }
        }
    }

    configurator._check_service_user_vcenter(
        "test_service_user_template", "test_service", "test_host", "test_path", "2"
    )

    configurator.vcenter_sso.list_service_users.called_once_with("test_host", "test_service_user_template", "mpw")

    # Should get deleted! 25 hours old
    configurator.vcenter_sso.delete_service_user.called_once_with("test_host", "test_service_user_template0001")

    assert configurator.vcenter_service_user_tracker == {
        "test_service": {
            "test_host": {
                "2": time_last_seen,
            }
        }
    }
