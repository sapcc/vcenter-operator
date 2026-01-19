import pytest

from unittest import mock

from vcenter_operator.vault import Vault
from vcenter_operator.vault_cache import NSXTManagementCache

@pytest.fixture
def vault():
    """Fixture to create a Vault instance with mocked dependencies"""
    vault = Vault(dry_run=False)
    return vault

def test_add_user(vault):
    region = "qa-de-1"
    caching_time = 1800

    key = "bb100"
    value = "supersecure"

    cacher = NSXTManagementCache(region, vault, caching_time)
    cacher[key] = value

    assert value == cacher[key]

def test_renew_pw(vault):
    region = "qa-de-1"
    caching_time = 0

    key = "bb100"
    value = "supersecure"

    cacher = NSXTManagementCache(region, vault, caching_time)
    cacher[key] = value

    with mock.patch('vcenter_operator.vault_cache.NSXTManagementCacher.renew_pw') as renew:
        renew.return_value = "new_supersecure"
        new_master_pw = cacher[key]


def test_no_pw(vault):
    cache = NSXTManagementCache(region="qa-de-1", vault=vault)

    key = "not_there"

    with pytest.raises(KeyError):
        cache[key]
