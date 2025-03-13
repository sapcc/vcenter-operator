from datetime import datetime, timedelta
from unittest.mock import MagicMock, call

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
    configurator.vault = MagicMock()
    configurator.vcenter_service_user_tracker = {}
    return configurator


def test_user_expired_1(configurator):
    """Test the check of a service-user that is expired"""

    configurator.vault.get_metadata.return_value = {
        "data": {
            "username": "test_service_user",
            "password": "test_password",
            "versions": {"1": {}, "2": {}, "3": {}},
            "custom_metadata": {
                "expiry_date": (datetime.now()).strftime("%Y-%m-%d"),
            },
        }
    }
    configurator.service_users = {"test_path": ["1", "2", "3"]}

    configurator.vault.create_service_user.return_value = ("4", "test_service_user", "test_password")

    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")

    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.create_service_user.assert_called_once_with(
        "test_service_user_template", "test_path", "test_service", "3"
    )

    assert configurator.service_users["test_path"] == ["1", "2", "3", "4"]


def test_user_expired_2(configurator):
    """Test the check of a service-user that is expired since 1 day"""

    configurator.vault.get_metadata.return_value = {
        "data": {
            "username": "test_service_user",
            "password": "test_password",
            "versions": {"1": {}, "2": {}, "3": {}, "4": {}},
            "custom_metadata": {
                "expiry_date": (datetime.now() + timedelta(days=89)).strftime("%Y-%m-%d"),
            },
        }
    }

    configurator.service_users = {"test_path": ["1", "2", "3", "4"]}

    configurator.vault.create_service_user.return_value = ("5", "test_service_user", "test_password")

    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")
    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.create_service_user.assert_called_once_with(
        "test_service_user_template", "test_path", "test_service", "4"
    )

    assert configurator.service_users["test_path"] == ["1", "2", "3", "4", "5"]


def test_user_expired_3(configurator):
    """
    Test the check of a service-user that is expired right now, but will be rotated because
    of the millis that pass till the function call
    """

    configurator.vault.get_metadata.return_value = {
        "data": {
            "username": "test_service_user",
            "password": "test_password",
            "versions": {"1": {}, "2": {}, "3": {}, "4": {}, "5": {}},
            "custom_metadata": {
                "expiry_date": (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
            },
        }
    }

    configurator.service_users = {"test_path": ["4", "5"]}
    configurator.vault.create_service_user.return_value = ("6", "test_service_user", "test_password")

    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")
    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.create_service_user.assert_called_once_with(
        "test_service_user_template", "test_path", "test_service", "5"
    )

    assert configurator.service_users["test_path"] == ["4", "5", "6"]


def test_user_not_expired_1(configurator):
    """
    Test the check of a service-user that is expired will expire in 91 days
    and will not be rotated
    """

    configurator.vault.get_metadata.return_value = {
        "data": {
            "username": "test_service_user",
            "password": "test_password",
            "versions": {"1": {}, "2": {}, "3": {}, "4": {}, "5": {}},
            "custom_metadata": {
                "expiry_date": (datetime.now() + timedelta(days=91)).strftime("%Y-%m-%d"),
            },
        }
    }

    configurator.service_users = {"test_path": ["4", "5"]}

    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")
    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.create_service_user.assert_not_called()

    assert configurator.service_users["test_path"] == ["4", "5"]
