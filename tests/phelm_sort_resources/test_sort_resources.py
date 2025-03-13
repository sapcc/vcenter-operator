import pytest

from vcenter_operator.phelm import DeploymentState


@pytest.fixture
def state():
    """Fixture to create a deployment state instance"""
    state = DeploymentState(dry_run=False)

    return state

def test_sort_resources_1(state):
    """Test the correct ordering of resources"""

    items = [
        {1: "ConfigMap"},
        {1: "ConfigMap"},
        {1: "Secret"},
        {1: "Secret"},
    ]

    sorted_items = state._sort_resources(items)

    expected_order = [
        {1: "Secret"},
        {1: "Secret"},
        {1: "ConfigMap"},
        {1: "ConfigMap"},
    ]

    assert sorted_items == expected_order

def test_sort_resources_2(state):
    """Test the correct ordering of resources"""

    items = [
        {1: "Deployment"},
        {1: "ConfigMap"},
        {1: "Secret"},
        {1: "Secret"},
    ]

    sorted_items = state._sort_resources(items)

    expected_order = [
        {1: "Secret"},
        {1: "Secret"},
        {1: "ConfigMap"},
        {1: "Deployment"},
    ]

    assert sorted_items == expected_order

def test_sort_resources_3(state):
    """Test the correct ordering of resources"""

    items = [
        {1: "ConfigMap"},
        {1: "Deployment"},
        {1: "Secret"},
        {1: "Deployment"},
    ]

    sorted_items = state._sort_resources(items)

    expected_order = [
        {1: "Secret"},
        {1: "ConfigMap"},
        {1: "Deployment"},
        {1: "Deployment"},
    ]

    assert sorted_items == expected_order

def test_sort_resources_4(state):
    """Test the correct ordering of resources"""

    items = [
        {1: "ConfigMap"},
        {1: "Service"},
        {1: "Deployment"},
    ]

    sorted_items = state._sort_resources(items)

    expected_order = [
        {1: "ConfigMap"},
        {1: "Deployment"},
        {1: "Service"},
    ]

    assert sorted_items == expected_order

def test_sort_resources_5(state):
    """Test the correct ordering of resources"""

    items = []

    sorted_items = state._sort_resources(items)

    expected_order = []

    assert sorted_items == expected_order

def test_sort_resources_6(state):
    """Test the correct ordering of resources"""

    items = [{1: "ConfigMap"},]

    sorted_items = state._sort_resources(items)

    expected_order = [{1: "ConfigMap"},]

    assert sorted_items == expected_order

def test_sort_resources_7(state):
    """Test the correct ordering of resources"""

    items = [
        {1: "Foo"},
        {1: "Bar"},
        {1: "Baz"},
    ]
    sorted_items = state._sort_resources(items)
    expected_order = [
        {1: "Foo"},
        {1: "Bar"},
        {1: "Baz"},
    ]
    assert sorted_items == expected_order
