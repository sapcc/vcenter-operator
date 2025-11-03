import time
from unittest.mock import MagicMock, patch

import pytest
from six import assertCountEqual

from vcenter_operator.configurator import Configurator
from vcenter_operator.nsxt_user_manager import NsxtUserAPIHelper

def create_configurator():
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


@patch.object(NsxtUserAPIHelper,"add_user_to_group")
@patch.object(NsxtUserAPIHelper,"create_service_user")
@patch.object(NsxtUserAPIHelper,"list_users")
@patch.object(NsxtUserAPIHelper,"check_users_in_group")
def test_service_user_missing_in_nsxt(fn_user_group, fn_list, fn_create_user, fn_add_usergroup):
    user = "admin"
    password = "admin"

    service_user_prefix = "userprefix"
    latest_version = "0002"
    service = "nsxt"
    bb = "bb085"
    region = "qa-de-1"
    path = f"{service}/{bb}"
    group = "blabbla"

    configurator = create_configurator()
    configurator.vault.get_secret.return_value = {
        "username": f"{service_user_prefix}{latest_version}",
        "password": "test_password",
    }

    fn_list.return_value = ["foo", "bar"]
    fn_user_group.return_value = True
    fn_create_user.return_value = True
    fn_add_usergroup.return_value = True

    configurator._check_nsxt_service_user(service_user_prefix, service, bb, path, latest_version, group)

    fn_list.assert_called_with(prefix=service_user_prefix)
    fn_create_user.assert_called_with(f"{service_user_prefix}{latest_version}", "test_password")
    fn_add_usergroup.assert_called_with(f"{service_user_prefix}{latest_version}", group)
    assert bb in configurator.vcenter_service_user_tracker[service]
    assert "2" in configurator.vcenter_service_user_tracker[service][bb]
    assert (
            configurator.vcenter_service_user_tracker[service][bb]["2"]
            < time.time()
    )


@patch.object(NsxtUserAPIHelper,"delete_service_user")
@patch.object(NsxtUserAPIHelper,"list_users")
@patch.object(NsxtUserAPIHelper,"check_users_in_group")
def test_stale_service_user(fn_user_group, fn_list, fn_delete):
    user = "admin"
    password = "admin"

    service_user_prefix = "userprefix"
    latest_version = "2"
    service = "nsxt"
    bb = "bb085"
    region = "qa-de-1"
    path = f"{service}/{bb}"

    configurator = create_configurator()
    configurator.vcenter_service_user_tracker = {
        service: {bb: {
               "1": 0,
               "2": 0
        }}
    }

    fn_list.return_value = [f"{service_user_prefix}{latest_version}", f"{service_user_prefix}001"]
    fn_user_group.return_value = True
    fn_delete.return_value = True
    configurator._check_nsxt_service_user(service_user_prefix, service, bb, path, latest_version)

    # Stale entry should be removed
    assert "1" not in configurator.vcenter_service_user_tracker[service][bb].keys(), \
        f"Expected user version '1' to be deleted"


