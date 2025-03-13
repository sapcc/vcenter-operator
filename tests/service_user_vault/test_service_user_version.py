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


def test_user_version_up_to_date(configurator):
    """Test the check of a service-user that has an up to date version"""

    configurator.vault.get_metadata.return_value = {
        "data": {
            "username": "test_service_user",
            "password": "test_password",
            "versions": {"1": {}, "2": {}, "3": {}},
            "custom_metadata": {
                "expiry_date": (datetime.now() + timedelta(days=91)).strftime("%Y-%m-%d"),
            },
        }
    }
    configurator.service_users = {"test_path": ["1", "2", "3"]}

    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")

    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.create_service_user.assert_not_called()
    configurator.vault.check_and_update_username_if_neccessary.assert_not_called()

    assert configurator.service_users["test_path"] == ["1", "2", "3"]


def test_user_newer_version(configurator):
    """Test the check of a service-user that has a newer version than in vcenter-operator state"""

    configurator.vault.get_metadata.return_value = {
        "data": {
            "username": "test_service_user",
            "password": "test_password",
            "versions": {"1": {}, "2": {}, "3": {}},
            "custom_metadata": {
                "expiry_date": (datetime.now() + timedelta(days=91)).strftime("%Y-%m-%d"),
            },
        }
    }

    configurator.service_users = {"test_path": ["1", "2"]}
    configurator.vault.check_and_update_username_if_neccessary.return_value = "3"
    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")

    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.check_and_update_username_if_neccessary.assert_called_once_with(
        "test_path", "test_service", "test_service_user_template")

    assert configurator.service_users["test_path"] == ["1", "2", "3"]


def test_user_smaller_version(configurator):
    """Test the check of a service-user that has a smaller version than in vcenter-operator state"""

    configurator.vault.get_metadata.return_value = {
        "data": {
            "username": "test_service_user",
            "password": "test_password",
            "versions": {"1": {}, "2": {}},
            "custom_metadata": {
                "expiry_date": (datetime.now() + timedelta(days=91)).strftime("%Y-%m-%d"),
            },
        }
    }

    configurator.service_users = {"test_path": ["1", "2", "3"]}
    configurator.vault.check_and_update_username_if_neccessary.return_value = "2"
    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")

    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.check_and_update_username_if_neccessary.assert_called_once_with(
        "test_path", "test_service", "test_service_user_template")

    assert configurator.service_users["test_path"] == ["1", "2", "3", "2"]
