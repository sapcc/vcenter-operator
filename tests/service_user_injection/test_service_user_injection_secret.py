import time

import pytest
from jinja2 import DictLoader, Environment

from vcenter_operator.phelm import DeploymentState
from vcenter_operator.templates import _b64enc, _ini_quote


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
kind: Secret
metadata:
  name: nova-compute-vmware-{= name =}
  labels:
    vcenter-operator-secret-version: {= service_user_version | quote =}
  annotations:
    uses-service-user: testservice
data:
  nova-compute-secrets.conf:{= " " =}
    {%- filter b64enc %}
  [vmware]
  host_username = {= username =}
  host_password = {= password =}
      {%- endfilter %}""",
        # Keeping this simple and test if the template is rendered with the values in host_username and host_password
        "test_template_2.yaml.j2": """apiVersion: v1
kind: Secret
metadata:
  name: nova-compute-vmware-{= name =}
data:
  nova-compute-secrets.conf:{= " " =}
    {%- filter b64enc %}
  [vmware]
  host_username = {= username =}
  host_password = {= password =}
      {%- endfilter %}""",
    }
    env = Environment(loader=DictLoader(templates))
    env.variable_start_string = "{="
    env.variable_end_string = "=}"
    env.filters["b64enc"] = _b64enc
    env.filters['quote'] = _ini_quote
    return env


def test_inject_user_info(state, jinja_env):
    """Test the injection of service-user information into a template"""

    # Load the template from the Jinja2 environment
    template = jinja_env.get_template("test_template.yaml.j2")

    service_users = {"test_region/vcenter-operator/testservice/test_vcenter": ["1"]}
    vcenter_service_user_tracker = {"testservice": {"test_vcenter": {"1": time.time()}}}
    options = {
        "name": "test_name",
        "vcenter_name": "test_vcenter",
        "region": "test_region",
        "host": "test_vcenter",
    }
    service_user_crds = {"testservice": {}}
    jinja2_options = {"uses-service-user": "testservice"}

    result = state._inject_service_user_info_and_render(
        template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    )

    assert (
        result
        == """apiVersion: v1
kind: Secret
metadata:
  name: nova-compute-vmware-test_name
  labels:
    vcenter-operator-secret-version: "1"
  annotations:
    uses-service-user: testservice
data:
  nova-compute-secrets.conf: CiAgW3Ztd2FyZV0KICBob3N0X3VzZXJuYW1lID0ge3sgcmVzb2x2ZSAidmF1bHQra3Z2MjovLy9zZWNyZXRzL3Rlc3RfcmVnaW9uL3ZjZW50ZXItb3BlcmF0b3IvdGVzdHNlcnZpY2UvdGVzdF92Y2VudGVyL3VzZXJuYW1lP3ZlcnNpb249MSIgfX1AdnNwaGVyZS5sb2NhbAogIGhvc3RfcGFzc3dvcmQgPSB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci90ZXN0c2VydmljZS90ZXN0X3ZjZW50ZXIvcGFzc3dvcmQ/dmVyc2lvbj0xIiB9fQ=="""
    )


def test_inject_user_info_vault_version_missing(state, jinja_env):
    """
    Test the injection of service-user information into a template
    Should not inject version 2 but 1 because 2 is missing in vault
    """

    # Load the template from the Jinja2 environment
    template = jinja_env.get_template("test_template.yaml.j2")

    service_users = {"test_region/vcenter-operator/testservice/test_vcenter": ["1", "2"]}
    vcenter_service_user_tracker = {"testservice": {"test_vcenter": {"1": time.time()}}}
    options = {
        "name": "test_name",
        "vcenter_name": "test_vcenter",
        "region": "test_region",
        "host": "test_vcenter",
    }
    service_user_crds = {"testservice": {}}
    jinja2_options = {"uses-service-user": "testservice"}

    result = state._inject_service_user_info_and_render(
        template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    )

    assert (
        result
        == """apiVersion: v1
kind: Secret
metadata:
  name: nova-compute-vmware-test_name
  labels:
    vcenter-operator-secret-version: "1"
  annotations:
    uses-service-user: testservice
data:
  nova-compute-secrets.conf: CiAgW3Ztd2FyZV0KICBob3N0X3VzZXJuYW1lID0ge3sgcmVzb2x2ZSAidmF1bHQra3Z2MjovLy9zZWNyZXRzL3Rlc3RfcmVnaW9uL3ZjZW50ZXItb3BlcmF0b3IvdGVzdHNlcnZpY2UvdGVzdF92Y2VudGVyL3VzZXJuYW1lP3ZlcnNpb249MSIgfX1AdnNwaGVyZS5sb2NhbAogIGhvc3RfcGFzc3dvcmQgPSB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci90ZXN0c2VydmljZS90ZXN0X3ZjZW50ZXIvcGFzc3dvcmQ/dmVyc2lvbj0xIiB9fQ=="""
    )


def test_inject_user_info_vault_2(state, jinja_env):
    """
    Test the injection of service-user information into a template
    Should now inject version 2
    """

    # Load the template from the Jinja2 environment
    template = jinja_env.get_template("test_template.yaml.j2")

    service_users = {"test_region/vcenter-operator/testservice/test_vcenter": ["1", "2"]}
    vcenter_service_user_tracker = {"testservice": {"test_vcenter": {"1": time.time(), "2": time.time()}}}
    options = {
        "name": "test_name",
        "vcenter_name": "test_vcenter",
        "region": "test_region",
        "host": "test_vcenter",
    }
    service_user_crds = {"testservice": {}}
    jinja2_options = {"uses-service-user": "testservice"}

    result = state._inject_service_user_info_and_render(
        template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    )

    assert (
        result
        == """apiVersion: v1
kind: Secret
metadata:
  name: nova-compute-vmware-test_name
  labels:
    vcenter-operator-secret-version: "2"
  annotations:
    uses-service-user: testservice
data:
  nova-compute-secrets.conf: CiAgW3Ztd2FyZV0KICBob3N0X3VzZXJuYW1lID0ge3sgcmVzb2x2ZSAidmF1bHQra3Z2MjovLy9zZWNyZXRzL3Rlc3RfcmVnaW9uL3ZjZW50ZXItb3BlcmF0b3IvdGVzdHNlcnZpY2UvdGVzdF92Y2VudGVyL3VzZXJuYW1lP3ZlcnNpb249MiIgfX1AdnNwaGVyZS5sb2NhbAogIGhvc3RfcGFzc3dvcmQgPSB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci90ZXN0c2VydmljZS90ZXN0X3ZjZW50ZXIvcGFzc3dvcmQ/dmVyc2lvbj0yIiB9fQ=="""
    )
