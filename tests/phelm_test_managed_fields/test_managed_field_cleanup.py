from unittest.mock import Mock, patch

import pytest

from vcenter_operator.phelm import DeploymentState


@pytest.fixture
def state():
    """Fixture to create a deployment state instance"""
    state = DeploymentState(dry_run=False)
    return state


@pytest.fixture
def mock_k8s_client():
    """Fixture to create a mock Kubernetes client"""
    client = Mock()
    return client


def create_managed_field(manager, operation):
    """Helper to create a managed field object"""
    field = Mock()
    field.manager = manager
    field.operation = operation
    return field


def create_k8s_object_with_managed_fields(name, namespace, managed_fields):
    """Helper to create a mock Kubernetes object with managed fields"""
    obj = Mock()
    obj.metadata = Mock()
    obj.metadata.name = name
    obj.metadata.namespace = namespace
    obj.metadata.managedFields = managed_fields
    return obj


def test_remove_managed_fields_kubectl_update(state, mock_k8s_client):
    """Test removal of kubectl Update managed fields"""
    # Setup mock managed fields
    managed_fields = [
        create_managed_field('kubectl', 'Apply'),
        create_managed_field('vcenter-operator', 'Update'),
    ]

    server_object = create_k8s_object_with_managed_fields(
        name='test-resource',
        namespace='default',
        managed_fields=managed_fields
    )

    # Mock client.get to return our server object
    mock_k8s_client.get.return_value = server_object

    # Mock the patch call
    mock_k8s_client.patch.return_value = None

    with patch.object(state, 'get_client', return_value=mock_k8s_client):
        resource = Mock()
        resource_args = {'namespace': 'default'}
        new_item = 'test-resource'

        state._clean_managed_fields(resource, resource_args, new_item)

    # Verify client.get was called
    mock_k8s_client.get.assert_called_once_with(
        resource,
        name='test-resource',
        namespace='default'
    )

    # Verify client.patch was called to remove the kubectl Update entry
    mock_k8s_client.patch.assert_called_once()
    call_args = mock_k8s_client.patch.call_args

    assert call_args[1]['name'] == 'test-resource'
    assert call_args[1]['namespace'] == 'default'
    assert call_args[1]['content_type'] == 'application/json-patch+json'

    # Check the patch removes index 0 (kubectl Update)
    patch_body = call_args[1]['body']
    assert len(patch_body) == 2
    assert patch_body[0]['op'] == 'remove'
    assert patch_body[0]['path'] == '/metadata/managedFields/1'


def test_remove_managed_fields_vcenter_operator_update(state, mock_k8s_client):
    """Test removal of vcenter-operator Update managed fields"""
    managed_fields = [
        create_managed_field('vcenter-operator', 'Update'),
        create_managed_field('vcenter-operator', 'Apply'),
    ]

    server_object = create_k8s_object_with_managed_fields(
        name='test-resource',
        namespace='default',
        managed_fields=managed_fields
    )

    mock_k8s_client.get.return_value = server_object
    mock_k8s_client.patch.return_value = None

    with patch.object(state, 'get_client', return_value=mock_k8s_client):
        resource = Mock()
        resource_args = {'namespace': 'default'}
        new_item = {'metadata': {'name': 'test-resource'}}

        state._clean_managed_fields(resource, resource_args, new_item)

    # Verify patch was called to remove vcenter-operator Update (index 0)
    mock_k8s_client.patch.assert_called_once()
    patch_body = mock_k8s_client.patch.call_args[1]['body']
    assert len(patch_body) == 1
    assert patch_body[0]['path'] == '/metadata/managedFields/0'


def test_remove_none_managed_fields(state, mock_k8s_client):
    """Test no removal when no unwanted managed fields exist"""
    managed_fields = [
        create_managed_field('vcenter-operator', 'Apply'),
        create_managed_field('my-custom-controller', 'Update'),
    ]

    server_object = create_k8s_object_with_managed_fields(
        name='test-resource',
        namespace='default',
        managed_fields=managed_fields
    )

    mock_k8s_client.get.return_value = server_object

    with patch.object(state, 'get_client', return_value=mock_k8s_client):
        resource = Mock()
        resource_args = {'namespace': 'default'}
        new_item = {'metadata': {'name': 'test-resource'}}

        state._clean_managed_fields(resource, resource_args, new_item)

    # Verify patch was NOT called since no unwanted fields exist
    mock_k8s_client.patch.assert_not_called()


def test_managed_fields_empty_list(state, mock_k8s_client):
    """Test handling when managed fields list is empty"""
    server_object = create_k8s_object_with_managed_fields(
        name='test-resource',
        namespace='default',
        managed_fields=[]
    )

    mock_k8s_client.get.return_value = server_object

    with patch.object(state, 'get_client', return_value=mock_k8s_client):
        resource = Mock()
        resource_args = {'namespace': 'default'}
        new_item = {'metadata': {'name': 'test-resource'}}

        state._clean_managed_fields(resource, resource_args, new_item)

    # Verify patch was NOT called
    mock_k8s_client.patch.assert_not_called()


def test_managed_fields_none(state, mock_k8s_client):
    """Test handling when managed fields is None"""
    server_object = create_k8s_object_with_managed_fields(
        name='test-resource',
        namespace='default',
        managed_fields=None
    )

    mock_k8s_client.get.return_value = server_object

    with patch.object(state, 'get_client', return_value=mock_k8s_client):
        resource = Mock()
        resource_args = {'namespace': 'default'}
        new_item = {'metadata': {'name': 'test-resource'}}

        state._clean_managed_fields(resource, resource_args, new_item)

    # Verify patch was NOT called
    mock_k8s_client.patch.assert_not_called()

