import io
import json
import logging
from collections import OrderedDict

import attr
import yaml
from jinja2.exceptions import TemplateError
from kubernetes import client as k8s_client
from kubernetes import dynamic
from yaml.error import YAMLError

from vcenter_operator.templates import env, vcenter_service_user_crd_loader

LOG = logging.getLogger(__name__)

RESOURCE_ORDER = {
    "Secret": 0,
    "ConfigMap": 1,
    "Deployment": 2,
}


class ServiceUserNotFoundError(Exception):
    """Raised when a required service-user or service-user path is missing for rendering."""
    pass


class ServiceUserPathNotFoundError(Exception):
    """Raised when a service-user path is not found in the service-user mapping."""
    pass


@attr.s
class DeploymentState:
    dry_run = attr.ib(default=False)
    items = attr.ib(default=attr.Factory(OrderedDict))
    actions = attr.ib(default=attr.Factory(OrderedDict))

    def render(self, scope, options, service_users, vcenter_service_user_tracker):
        template_names = env.list_templates(filter_func=lambda x: (x.startswith(scope) and x.endswith(".yaml.j2")))
        service_user_crds = vcenter_service_user_crd_loader.get_mapping()
        for template_name in template_names:
            try:
                template = env.get_template(template_name)
                # e.g. vcenter_cluster/namespace/cr-name
                namespace = template_name.split("/")[1]
                jinja2_options = env.get_jinja2_options(template_name)
                result = self._inject_service_user_info_and_render(
                    template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
                )
                owner = env.get_source_owner(template_name)
                self.add(result, owner, namespace)
            except (TemplateError, YAMLError):
                LOG.exception("Failed to render %s", template_name)
        # Order the item by kind to ensure that Secrets are created before ConfigMaps and Deployments
        self.order_items()

    def _inject_service_user_info_and_render(
        self, template, service_users, vcenter_service_user_tracker, service_user_crds, options, jinja2_options
    ):
        """Check if template uses service-user and inject necessary information into the template"""

        if "uses-service-user" not in jinja2_options:
            LOG.debug("Template %s does not require service-user management", template.name)
            return template.render(options)

        service_name = jinja2_options["uses-service-user"]
        service_user_path = f"{options['region']}/vcenter-operator/{service_name}/{options['vcenter_name']}"

        if service_name not in service_user_crds:
            # This exception should not get caught - intention is to raise attention to the missing service-user CR
            raise ServiceUserNotFoundError(f"Service vcsu {service_name} missing for template {template.name}")

        if service_user_path not in service_users:
            raise ServiceUserPathNotFoundError(
                f"Service-user path for service {service_name} and vcenter {options['vcenter_name']} not found")

        latest_version = self._get_latest_active_service_user_version(
            service_name,
            options["host"],
            service_users[service_user_path],
            vcenter_service_user_tracker,
        )
        options["service_user_version"] = latest_version

        # Create the service-user username and password paths for secrets-injector
        # Should only be used for resource Secret
        # Only the path gets exposed on missconfigured VCTs due to the secrets-injector
        username_path = (
            "{{ "
            f'resolve "vault+kvv2:///secrets/{service_user_path}/username?version={options["service_user_version"]}"'
            " }}@vsphere.local"
        )
        password_path = (
            "{{ "
            f'resolve "vault+kvv2:///secrets/{service_user_path}/password?version={options["service_user_version"]}"'
            " }}"
        )

        options["username"] = username_path
        options["password"] = password_path

        result = template.render(options)

        # Remove the service-user info to not render it accidentially somewhere else
        del options["username"]
        del options["password"]
        del options["service_user_version"]

        return result

    def _get_latest_active_service_user_version(
        self, service_name, vcenter_name, service_user_versions, vcenter_service_user_tracker
    ):
        """Return the latest service-user version for the given service and vcenter"""
        for service_user in reversed(service_user_versions):
            if service_user in vcenter_service_user_tracker[service_name][vcenter_name]:
                return service_user

    def add(self, result, owner, namespace):
        stream = io.StringIO(result)
        for item in yaml.safe_load_all(stream):
            if owner:
                item["metadata"]["ownerReferences"] = [owner]
            _id = (item['apiVersion'], item['kind'], item['metadata']['name'], namespace)
            if _id in self.items:
                LOG.warning(f"Duplicate item #{_id}")
            self.items[_id] = item

    def delta(self, other):
        delta = DeploymentState()
        for k in self.items.keys() - other.items.keys():
            delta.actions[k] = 'delete'
        for k in (self.items.keys() & other.items.keys()):
            if self.items[k] != other.items[k]:
                delta.actions[k] = 'update'
                delta.items[k] = other.items[k]
            # Nothing to do otherwise
        for k in (self.items.keys() - other.items.keys()):
            delta.items[k] = other.items[k]

        delta.order_items()
        return delta

    def _sort_resources(self, items):
        """
        Sort the resources in the order defined by RESOURCE_ORDER.
        This is important to ensure that Secrets are created before ConfigMaps and Deployments.
        """
        return sorted(
            items,
            key=lambda x: RESOURCE_ORDER.get(x[1], len(RESOURCE_ORDER)),
        )

    def order_items(self):
        """
        Orders self.items (an OrderedDict) by resource kind using RESOURCE_ORDER.
        """
        sorted_keys = self._sort_resources(self.items.keys())
        self.items = OrderedDict((k, self.items[k]) for k in sorted_keys)

    def _apply_item(self, resource, resource_args, new_item):
        client = self.get_client()
        metadata_name = new_item['metadata']['name']

        if self.dry_run:
            LOG.info(f"Applying: {resource}/{metadata_name} in {resource_args['namespace']}")
            for line in json.dumps(
                    new_item, sort_keys=True,
                    indent=2, separators=(',', ': ')).splitlines():
                LOG.debug(line)
        else:
            LOG.debug(f"Applying: {resource}/{metadata_name} in {resource_args['namespace']}")

        # If anything has changed, the server will trigger it
        try:
            # Note: applies --dry-run if it's enabled in resource_args
            client.server_side_apply(resource, new_item,
                                    force_conflicts=True,  # Sole controller
                                    **resource_args)
        except dynamic.exceptions.UnprocessibleEntityError:
            # If the server can't patch it, try to replace it
            LOG.info(f"Replacing: {resource}/{metadata_name} in {resource_args['namespace']}")
            # Note: applies --dry-run if it's enabled in resource_args
            client.replace(resource, new_item, **resource_args)

    @staticmethod
    def get_client():
        return dynamic.DynamicClient(k8s_client.api_client.ApiClient())

    @staticmethod
    def get_resource(*, api_version=None, kind=None):
        client = DeploymentState.get_client()
        return client.resources.get(api_version=api_version, kind=kind)

    def _id_to_k8s(self, api_version, kind, name, namespace):
        resource = self.get_resource(api_version=api_version, kind=kind)

        resource_args = {
            'name': name,
            'field_manager': 'vcenter-operator',
        }

        if resource.namespaced:
            resource_args['namespace'] = namespace

        if self.dry_run:
            resource_args['dry_run'] = "All"

        return resource, resource_args

    def apply(self):
        retry_list = []
        client = self.get_client()

        for (api_version, kind, name, namespace), target in self.items.items():
            resource, resource_args = self._id_to_k8s(api_version, kind, name, namespace)
            try:
                self._apply_item(resource, resource_args, target)
            except k8s_client.rest.ApiException as e:
                if e.status == 422:
                    retry_list.append((resource, resource_args, target))
                else:
                    raise

        for resource, resource_args, target in retry_list:
            try:
                self._apply_item(resource, resource_args, target)
            except k8s_client.rest.ApiException:
                LOG.exception("Could not apply change")

        for (api_version, kind, name, namespace), action in self.actions.items():
            if action != 'delete':
                continue

            resource, resource_args = self._id_to_k8s(api_version, kind, name, namespace)
            try:
                LOG.debug(f"Delete: {resource}/{name} in {namespace}")
                client.delete(resource, **resource_args)
            except k8s_client.rest.ApiException as e:
                if e.status == 404:
                    pass
                else:
                    raise
