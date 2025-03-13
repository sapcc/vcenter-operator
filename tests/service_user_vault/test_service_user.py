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


def test_user_not_in_vault(configurator):
    """Test the check of a service-user that is not in vault"""

    configurator.vault.get_metadata.return_value = None
    configurator.vault.create_service_user.return_value = ("1", "test_service_user", "test_password")

    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")

    expected_calls = [call("test_path", read=False)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.create_service_user.assert_called_once_with(
        "test_service_user_template", "test_path", "test_service"
    )

    assert configurator.service_users["test_path"] == ["1"]



def test_user_not_in_state(configurator):
    """Test the check of a service-user that is not in vcenter-operator state yet"""

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

    configurator.service_users = {}
    configurator.vault.check_and_update_username_if_neccessary.return_value = "3"
    configurator._check_service_user_vault("test_path", "test_service_user_template", "test_service")

    expected_calls = [call("test_path", read=False), call("test_path", read=True)]
    assert configurator.vault.get_metadata.call_args_list == expected_calls
    configurator.vault.check_and_update_username_if_neccessary.assert_called_once_with(
        "test_path", "test_service", "test_service_user_template")

    assert configurator.service_users["test_path"] == ["3"]


def test_user_valid(configurator):
    """Test the check of a service-user that is valid"""

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
    configurator.vault.check_and_update_username_if_neccessary.assert_not_called()
    configurator.vault.create_service_user.assert_not_called()

    assert configurator.service_users["test_path"] == ["1", "2", "3"]
