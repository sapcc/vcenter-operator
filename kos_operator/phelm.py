import io
import json
import logging
from operator import itemgetter

import attr
import yaml
from kubernetes import client as k8s_client
from kubernetes import dynamic

LOG = logging.getLogger(__name__)


@attr.s
class DeploymentState:
    namespace = attr.ib()
    dry_run = attr.ib(default=False)
    items = attr.ib(default=attr.Factory(dict))
    actions = attr.ib(default=attr.Factory(dict))

    def add(self, result, owner):
        stream = io.StringIO(result)
        for item in yaml.safe_load_all(stream):
            if owner:
                item["metadata"]["ownerReferences"] = [owner]
            _id = (item['apiVersion'], item['kind'], item['metadata']['name'])
            if _id in self.items:
                LOG.warning("Duplicate item #{}".format(_id))
            self.items[_id] = item

    def delta(self, other):
        delta = DeploymentState(namespace=self.namespace)
        # no ordering necessary for delete
        for k in self.items.keys() - other.items.keys():
            delta.actions[k] = 'delete'
        # sort by (kind, name), so we update ConfigMaps before Deployments, so
        # that restarting pods can read the new ConfigMaps already
        for k in sorted(self.items.keys() & other.items.keys(),
                        key=itemgetter(1, 2)):
            if self.items[k] != other.items[k]:
                delta.actions[k] = 'update'
                delta.items[k] = other.items[k]
            # Nothing to do otherwise
        # sort by (kind, name), so we update ConfigMaps before Deployments, so
        # that restarting pods can read the new ConfigMaps already
        for k in sorted(other.items.keys() - self.items.keys(),
                        key=itemgetter(1, 2)):
            delta.items[k] = other.items[k]

        return delta


    def _apply_item(self, resource, resource_args, new_item):
        client = self.get_client()
        metadata_name = new_item['metadata']['name']

        # If anything has changed, the server will trigger it
        client.server_side_apply(resource, new_item,
                                 force_conflicts=True,  # Sole controller
                                 **resource_args)
        if self.dry_run:
            LOG.info("Apply: {}/{}".format(resource, metadata_name))
            for line in json.dumps(
                    new_item, sort_keys=True,
                    indent=2, separators=(',', ': ')).splitlines():
                LOG.debug(line)
        else:
            LOG.debug("Apply: {}/{}".format(resource, metadata_name))

    @staticmethod
    def get_client():
        return dynamic.DynamicClient(k8s_client.api_client.ApiClient())

    @staticmethod
    def get_resource(*, api_version=None, kind=None):
        client = DeploymentState.get_client()
        return client.resources.get(api_version=api_version, kind=kind)


    def _id_to_k8s(self, api_version, kind, name):
        resource = self.get_resource(api_version=api_version, kind=kind)

        resource_args = {
            'name': name,
            'field_manager': 'kos-operator',
        }

        if resource.namespaced:
            resource_args['namespace'] = self.namespace

        if self.dry_run:
            resource_args['dry_run'] = "All"

        return resource, resource_args


    def apply(self):
        retry_list = []
        client = self.get_client()

        for (api_version, kind, name), target in self.items.items():
            resource, resource_args = self._id_to_k8s(api_version, kind, name)
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

        for (api_version, kind, name), action in self.actions.items():
            if action != 'delete':
                continue

            resource, resource_args = self._id_to_k8s(api_version, kind, name)
            try:
                LOG.debug("Delete: {}/{}".format(resource, name))
                client.delete(resource, name, **resource_args)
            except k8s_client.rest.ApiException as e:
                if e.status == 404:
                    pass
                else:
                    raise
