import time
import unittest
from unittest.mock import MagicMock, patch

from vcenter_operator.configurator import Configurator
from vcenter_operator.nsxt_user_manager import NsxtUserAPIHelper


class TestNsxtServiceUserManagement(unittest.TestCase):
    def setUp(self):
        global_options = {
            "dry_run": False,
        }
        domain = "test_domain"

        self.configurator = Configurator(domain, global_options)
        self.configurator.vcenter_sso = MagicMock()
        self.configurator.vault = MagicMock()
        self.configurator.vcenter_service_user_tracker = {}

    @patch.object(NsxtUserAPIHelper, "connect")
    @patch.object(NsxtUserAPIHelper, "add_user_to_group")
    @patch.object(NsxtUserAPIHelper, "create_service_user")
    @patch.object(NsxtUserAPIHelper, "list_users")
    @patch.object(NsxtUserAPIHelper, "check_users_in_group")
    def test_service_user_missing_in_nsxt(self, fn_user_group, fn_list, fn_create_user, fn_add_usergroup, fn_connect):
        management_user_secret = {
            "username": "admin",
            "password": "admin"
        }

        service_user_prefix = "userprefix"
        latest_version = "0002"
        service = "nsxt"
        bb = "bb085"
        region = "qa-de-1"
        path = f"{service}/{bb}"
        group = "blabbla"

        self.configurator.vault.get_secret.return_value = {
            "username": f"{service_user_prefix}{latest_version}",
            "password": "test_password",
        }

        fn_list.return_value = ["foo"]
        fn_user_group.return_value = True
        fn_create_user.return_value = True
        fn_add_usergroup.return_value = True
        fn_connect.return_value = True

        self.configurator._check_service_user_nsxt(service_user_prefix, service, region, bb, path, latest_version,
                                              management_user_secret, group)

        fn_list.assert_called_with(prefix=service_user_prefix)
        fn_create_user.assert_called_with(f"{service_user_prefix}{latest_version}", "test_password")
        fn_add_usergroup.assert_called_with(f"{service_user_prefix}{latest_version}", group)
        assert bb in self.configurator.vcenter_service_user_tracker[service]
        assert "2" in self.configurator.vcenter_service_user_tracker[service][bb]
        assert (
            self.configurator.vcenter_service_user_tracker[service][bb]["2"]
            < time.time()
        )


    @patch.object(NsxtUserAPIHelper, "delete_service_user")
    @patch.object(NsxtUserAPIHelper, "list_users")
    @patch.object(NsxtUserAPIHelper, "check_users_in_group")
    def test_stale_service_user(self, fn_user_group, fn_list, fn_delete):
        management_user_secret = {
            "username": "admin",
            "password": "admin"
        }

        service_user_prefix = "userprefix"
        latest_version = "2"
        service = "nsxt"
        bb = "bb085"
        region = "qa-de-1"
        path = f"{service}/{bb}"
        group = "blabbla"

        self.configurator.vcenter_service_user_tracker = {
            service: {bb: {
                "1": 0,
                "2": 0
            }}
        }

        fn_list.return_value = [f"{service_user_prefix}{latest_version.zfill(4)}", f"{service_user_prefix}001"]
        fn_user_group.return_value = True
        fn_delete.return_value = True
        self.configurator._check_service_user_nsxt(service_user_prefix, service, region, bb, path, latest_version,
                                              management_user_secret, group)

        # Stale entry should be removed
        assert "1" not in self.configurator.vcenter_service_user_tracker[service][bb].keys(), \
            "Expected user version '1' to be deleted"
