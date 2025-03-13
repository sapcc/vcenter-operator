import time
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.models import V1ObjectMeta, V1Pod, V1PodList

from vcenter_operator.configurator import Configurator
from vcenter_operator.templates import vcenter_service_user_crd_loader


@pytest.fixture
def configurator():
    """Fixture to create a Configurator instance with mocked dependencies"""
    global_options = {
        "dry_run": False,
        "own_namespace": "test_namespace",
        "manage_service_user_passwords": True,
    }
    domain = "test_domain"

    configurator = Configurator(domain, global_options)
    configurator.vcenter_service_user_tracker = {}
    configurator.api = MagicMock()

    vcenter_service_user_crd_loader.get_mapping = MagicMock()

    return configurator


def test_update_last_seen_of_valid_pod(configurator):
    """Test the update of a valid pod"""
    old_last_seen = time.time()

    configurator.vcenter_service_user_tracker = {
        "test_service": {"test_host": {"test_service_user_template0001": old_last_seen}}
    }

    vcenter_service_user_crd_loader.get_mapping.return_value = {"test_service": ("", "test_service_user_template", "")}
    pod = V1Pod(
        metadata=V1ObjectMeta(
            annotations={"uses-service-user": "test_service"},
            labels={"vcenter": "test_host", "vcenter-operator-secret-version": "1"},
        )
    )
    pod_list = V1PodList(items=[pod])
    with patch("kubernetes.client.CoreV1Api") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.list_namespaced_pod.return_value = pod_list
        mock_api_cls.return_value = mock_api

        configurator._check_pods_and_update_service_user_tracker()

    assert "test_host" in configurator.vcenter_service_user_tracker["test_service"]
    assert "1" in configurator.vcenter_service_user_tracker["test_service"]["test_host"]
    assert (
        configurator.vcenter_service_user_tracker["test_service"]["test_host"]["1"]
        > old_last_seen
    )


def test_update_last_seen_of_valid_pod_wrong_version(configurator):
    """Test the update of a valid pod but with a wrong version"""
    old_last_seen = time.time()

    configurator.vcenter_service_user_tracker = {
        "test_service": {"test_host": {"1": old_last_seen}}
    }

    vcenter_service_user_crd_loader.get_mapping.return_value = {"test_service": ("", "test_service_user_template", "")}
    pod = V1Pod(
        metadata=V1ObjectMeta(
            annotations={"uses-service-user": "test_service"},
            labels={"vcenter": "test_host", "vcenter-operator-secret-version": "2"},
        )
    )
    pod_list = V1PodList(items=[pod])
    with patch("kubernetes.client.CoreV1Api") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.list_namespaced_pod.return_value = pod_list
        mock_api_cls.return_value = mock_api

        configurator._check_pods_and_update_service_user_tracker()

    assert "test_host" in configurator.vcenter_service_user_tracker["test_service"]
    assert "1" in configurator.vcenter_service_user_tracker["test_service"]["test_host"]
    assert (
        configurator.vcenter_service_user_tracker["test_service"]["test_host"]["1"]
        == old_last_seen
    )
    assert "2" in configurator.vcenter_service_user_tracker["test_service"]["test_host"]
    assert (
        configurator.vcenter_service_user_tracker["test_service"]["test_host"]["2"]
        > old_last_seen
    )
