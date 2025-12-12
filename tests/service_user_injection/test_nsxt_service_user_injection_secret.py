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
  name: neutron-ml2-nsxv3-{= name =}
  labels:
    vcenter: {= host =}
    vcenter-operator-secret-version: {= service_user_version | quote =}
  annotations:
    uses-service-user: nsxt
data:
  NSXV3_LOGIN_USER: {= username =}
  NSXV3_LOGIN_PASSWORD: {= password =}
  neutron-nsxv3-secrets.conf:{= " " =}
  {%- filter b64enc %}
  [NSXV3]
  nsxv3_login_user = {= username =}
  nsxv3_login_password =  {= password =}
  {%- endfilter %}"""
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
kind: Secret
metadata:
  name: neutron-ml2-nsxv3-bb085
  labels:
    vcenter: test_vcenter
    vcenter-operator-secret-version: "1"
  annotations:
    uses-service-user: nsxt
data:
  NSXV3_LOGIN_USER: {{ resolve "vault+kvv2:///secrets/test_region/vcenter-operator/nsxt/bb085/username?version=1" }}
  NSXV3_LOGIN_PASSWORD: {{ resolve "vault+kvv2:///secrets/test_region/vcenter-operator/nsxt/bb085/password?version=1" }}
  neutron-nsxv3-secrets.conf: CiAgW05TWFYzXQogIG5zeHYzX2xvZ2luX3VzZXIgPSB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci9uc3h0L2JiMDg1L3VzZXJuYW1lP3ZlcnNpb249MSIgfX0KICBuc3h2M19sb2dpbl9wYXNzd29yZCA9ICB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci9uc3h0L2JiMDg1L3Bhc3N3b3JkP3ZlcnNpb249MSIgfX0="""
    )


def test_inject_user_info_vault_version_missing(state, jinja_env):
    """
    Test the injection of service-user information into a template
    Should not inject version 2 but 1 because 2 is missing in vault
    """

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
kind: Secret
metadata:
  name: neutron-ml2-nsxv3-bb085
  labels:
    vcenter: test_vcenter
    vcenter-operator-secret-version: "1"
  annotations:
    uses-service-user: nsxt
data:
  NSXV3_LOGIN_USER: {{ resolve "vault+kvv2:///secrets/test_region/vcenter-operator/nsxt/bb085/username?version=1" }}
  NSXV3_LOGIN_PASSWORD: {{ resolve "vault+kvv2:///secrets/test_region/vcenter-operator/nsxt/bb085/password?version=1" }}
  neutron-nsxv3-secrets.conf: CiAgW05TWFYzXQogIG5zeHYzX2xvZ2luX3VzZXIgPSB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci9uc3h0L2JiMDg1L3VzZXJuYW1lP3ZlcnNpb249MSIgfX0KICBuc3h2M19sb2dpbl9wYXNzd29yZCA9ICB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci9uc3h0L2JiMDg1L3Bhc3N3b3JkP3ZlcnNpb249MSIgfX0="""
    )


def test_inject_user_info_vault_2(state, jinja_env):
    """
    Test the injection of service-user information into a template
    Should now inject version 2
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
kind: Secret
metadata:
  name: neutron-ml2-nsxv3-bb085
  labels:
    vcenter: test_vcenter
    vcenter-operator-secret-version: "2"
  annotations:
    uses-service-user: nsxt
data:
  NSXV3_LOGIN_USER: {{ resolve "vault+kvv2:///secrets/test_region/vcenter-operator/nsxt/bb085/username?version=2" }}
  NSXV3_LOGIN_PASSWORD: {{ resolve "vault+kvv2:///secrets/test_region/vcenter-operator/nsxt/bb085/password?version=2" }}
  neutron-nsxv3-secrets.conf: CiAgW05TWFYzXQogIG5zeHYzX2xvZ2luX3VzZXIgPSB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci9uc3h0L2JiMDg1L3VzZXJuYW1lP3ZlcnNpb249MiIgfX0KICBuc3h2M19sb2dpbl9wYXNzd29yZCA9ICB7eyByZXNvbHZlICJ2YXVsdCtrdnYyOi8vL3NlY3JldHMvdGVzdF9yZWdpb24vdmNlbnRlci1vcGVyYXRvci9uc3h0L2JiMDg1L3Bhc3N3b3JkP3ZlcnNpb249MiIgfX0="""
    )
