import time

import pytest
from jinja2 import DictLoader, Environment

from vcenter_operator.phelm import DeploymentState
from vcenter_operator.templates import _ini_quote


@pytest.fixture
def state():
    """Fixture to create a DeploymentState instance"""
    state = DeploymentState(dry_run=False)

    return state


@pytest.fixture
def jinja_env():
    """Fixture to create a jinja2 environment with a mock template loader"""
    templates = {
        "test_template.yaml.j2": """apiVersion: v1
kind: Deployment
metadata:
  name: neutron-nsxv3-agent-{= name =}
  labels:
    vcenter: {= host =}
    vcenter-operator-secret-version: {= service_user_version | quote =}
  annotations:
    uses-service-user: nsxt
spec:
  replicas: 1""",
        "test_template_2.yaml.j2": """apiVersion: v1
kind: Deployment
metadata:
  name: neutron-nsxv3-agent-{= name =}
spec:
  replicas: 1""",
    }
    env = Environment(loader=DictLoader(templates))
    env.variable_start_string = "{="
    env.variable_end_string = "=}"
    env.filters['quote'] = _ini_quote
    return env


def test_inject_user_info(state, jinja_env):
    """Test the injection of service-user information into a template"""

    # Load the template from the Jinja2 environment
    template = jinja_env.get_template("test_template.yaml.j2")

    service_users = {"test_region/vcenter-operator/nsxt/bb085": ["1"]}
    vcenter_service_user_tracker = {"nsxt": {"bb085": {"1": time.time()}}}
    options = {
        "name": "bb085",
        "vcenter_name": "test_vcenter",
        "region": "test_region",
        "host": "test_vcenter",
    }
    service_user_crds = {"nsxt": {}}
    jinja2_options = {"uses-service-user": "nsxt"}

    result = state._inject_service_user_info_and_render(
        template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    )

    assert (
        result
        == """apiVersion: v1
kind: Deployment
metadata:
  name: neutron-nsxv3-agent-bb085
  labels:
    vcenter: test_vcenter
    vcenter-operator-secret-version: "1"
  annotations:
    uses-service-user: nsxt
spec:
  replicas: 1"""
    )


def test_inject_user_info_vault_version_missing(state, jinja_env):
    """Test the injection of service-user information into a template"""

    # Load the template from the Jinja2 environment
    template = jinja_env.get_template("test_template.yaml.j2")

    service_users = {"test_region/vcenter-operator/nsxt/bb085": ["1", "2"]}
    vcenter_service_user_tracker = {"nsxt": {"bb085": {"1": time.time()}}}
    options = {
        "name": "bb085",
        "vcenter_name": "test_vcenter",
        "region": "test_region",
        "host": "test_vcenter",
    }
    service_user_crds = {"nsxt": {}}
    jinja2_options = {"uses-service-user": "nsxt"}

    result = state._inject_service_user_info_and_render(
        template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    )

    assert (
        result
        == """apiVersion: v1
kind: Deployment
metadata:
  name: neutron-nsxv3-agent-bb085
  labels:
    vcenter: test_vcenter
    vcenter-operator-secret-version: "1"
  annotations:
    uses-service-user: nsxt
spec:
  replicas: 1"""
    )


def test_inject_user_info_vault_2(state, jinja_env):
    """
    Test the injection of service-user information into a template
    Should inject version 2
    """

    # Load the template from the Jinja2 environment
    template = jinja_env.get_template("test_template.yaml.j2")

    service_users = {"test_region/vcenter-operator/nsxt/bb085": ["1", "2"]}
    vcenter_service_user_tracker = {"nsxt": {"bb085": {"1": time.time(), "2": time.time()}}}
    options = {
        "name": "bb085",
        "vcenter_name": "test_vcenter",
        "region": "test_region",
        "host": "test_vcenter",
    }
    service_user_crds = {"nsxt": {}}
    jinja2_options = {"uses-service-user": "nsxt"}

    result = state._inject_service_user_info_and_render(
        template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    )

    assert (
        result
        == """apiVersion: v1
kind: Deployment
metadata:
  name: neutron-nsxv3-agent-bb085
  labels:
    vcenter: test_vcenter
    vcenter-operator-secret-version: "2"
  annotations:
    uses-service-user: nsxt
spec:
  replicas: 1"""
    )


def test_not_inject_user_info(state, jinja_env):
    """
    Test the injection of service-user information into an old template
    Should not inject version
    """

    # Load the template from the Jinja2 environment
    template = jinja_env.get_template("test_template_2.yaml.j2")

    service_users = {"test_region/vcenter-operator/nsxt/bb085": ["1", "2"]}
    vcenter_service_user_tracker = {"nsxt": {"bb085": {"1": time.time(), "2": time.time()}}}
    options = {
        "name": "bb085",
        "vcenter_name": "test_vcenter",
        "region": "test_region",
        "username": "testuser",
        "password": "testpassword",
        "host": "test_vcenter",
    }
    service_user_crds = {"nsxt": {}}
    jinja2_options = {"uses-service-user": "nsxt"}

    result = state._inject_service_user_info_and_render(
        template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    )

    assert (
        result
        == """apiVersion: v1
kind: Deployment
metadata:
  name: neutron-nsxv3-agent-bb085
spec:
  replicas: 1"""
    )
