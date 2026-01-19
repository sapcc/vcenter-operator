from unittest import mock

import pytest

from vcenter_operator.vault import Vault
from vcenter_operator.vault_cache import NSXTCacheError, NSXTManagementCache


@pytest.fixture
def cacher():
    """Fixture to create a Caching instance with mocked dependencies"""
    vault = Vault(dry_run=False)
    region = "blabla"
    caching_time = 18000

    cacher = NSXTManagementCache(region, vault, caching_time)
    return cacher

def test_add_user(cacher):
    key = "bb100"
    value = {"password": "supersecure", "username": "user"}

    with mock.patch('vcenter_operator.vault_cache.NSXTManagementCache.renew_pw') as renew:
        renew.return_value = value
        secret = cacher.get_secret(key)

    assert value["password"] == secret["password"]
    assert value["username"] == secret["username"]

def test_cached_pw(cacher):
    key = "bb100"

    # Set secret
    with mock.patch('vcenter_operator.vault.Vault.get_secret') as renew:
        renew.return_value = {"password": "new_supersecure", "username": "user"}
        cacher.get_secret(key)

    secret = cacher.get_secret(key)
    assert "new_supersecure" == secret["password"]

def test_expired_pw(cacher):
    caching_time = -1000
    key = "bb100"

    value = {"password": "supersecure", "username": "user"}
    cacher.cache_lifetime = caching_time

    # Set secret
    with mock.patch('vcenter_operator.vault.Vault.get_secret') as renew:
        renew.return_value = value
        cacher.get_secret(key)

    with mock.patch('vcenter_operator.vault.Vault.get_secret') as renew:
        renew.return_value =  {"password": "new_supersecure", "username": "user"}
        new_secret = cacher.get_secret(key)
        assert "new_supersecure" == new_secret["password"]

def test_return_old_cached_pw(cacher):
    key = "radomKey"
    value = {"password": "supersecure", "username": "user"}

    # Set secret
    with mock.patch('vcenter_operator.vault.Vault.get_secret') as inital_pw:
        inital_pw.return_value = value
        cacher.get_secret(key)

    # Return cached pw instead of raising an exception
    with mock.patch('vcenter_operator.vault.Vault.get_secret') as new_pw:
        new_pw.side_effect = NSXTCacheError("Simulate vault failure")
        old_cached_pw = cacher.get_secret(key)
        assert value["password"] == old_cached_pw["password"]
        assert value["username"] == old_cached_pw["username"]
