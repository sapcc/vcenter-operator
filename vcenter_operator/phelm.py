import json
import logging
import re
import sys

import attr
import jsonpatch
import six
import yaml
from jsonpointer import resolve_pointer
from kubernetes import client

LOG = logging.getLogger(__name__)

api_client = client.ApiClient()


def _remove_empty_from_dict(d):
    if type(d) is dict:
        return dict(
            (k, _remove_empty_from_dict(v)) for k, v in d.iteritems() if
            v and _remove_empty_from_dict(v))
    elif type(d) is list:
        return [_remove_empty_from_dict(v) for v in d if
                v and _remove_empty_from_dict(v)]
    else:
        return d


def _under_score(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


_IGNORE_PATHS = set(['/status', '/metadata/annotations', '/spec/selector'])


def serialize(obj):
    return _remove_empty_from_dict(api_client.sanitize_for_serialization(obj))


@attr.s
class DeploymentState(object):
    namespace = attr.ib()
    dry_run = attr.ib(default=False)
    items = attr.ib(default=attr.Factory(dict))
    actions = attr.ib(default=attr.Factory(dict))

    def add(self, result):
        stream = six.StringIO(result)
        for item in yaml.safe_load_all(stream):
            id = (item['apiVersion'], item['kind'], item['metadata']['name'])
            if id in self.items:
                LOG.warning("Duplicate item #{}".format(id))
            api = [p.capitalize() for p in id[0].split('/', 1)]
            klass = getattr(client, "".join(api + [id[1]]))
            try:
                ser = api_client._ApiClient__deserialize_model(item, klass)
                self.items[id] = serialize(ser)
            except AttributeError:
                LOG.error("Failed to deserialize model {} {}".format(
                    klass, item
                ))

    def delta(self, other):
        delta = DeploymentState(namespace=self.namespace)
        for k in six.viewkeys(self.items) - six.viewkeys(other.items):
            delta.actions[k] = 'delete'
        for k in six.viewkeys(self.items) & six.viewkeys(other.items):
            if self.items[k] != other.items[k]:
                delta.actions[k] = 'update'
                delta.items[k] = other.items[k]
            # Nothing to do otherwise
        for k in six.viewkeys(other.items) - six.viewkeys(self.items):
            delta.items[k] = other.items[k]

        return delta

    @staticmethod
    def _unique_items(l):
        return [dict(t) for t in set([tuple(d.items()) for d in l])]

    def _diff(self, old_item, new_item):
        if not new_item:
            return None
        if not old_item and new_item:
            return new_item

        diff = []
        skipped = []
        for op in jsonpatch.JsonPatch.from_diff(old_item, new_item):
            if op["op"] == "replace" and op["value"] is None \
                    or old_item.get("metadata", {}).get("namespace") is None \
                    and op["path"] == "/metadata/namespace" \
                    and op["value"] == self.namespace \
                    or op["path"] in _IGNORE_PATHS:
                skipped.append(op)
                continue

            if op["op"] == "remove":
                old_value = resolve_pointer(old_item, op["path"])
                if not isinstance(old_value, (dict, list)):
                    skipped.append(op)
                    continue

            diff.append(op)

        for op in skipped:
            if op["op"] != "remove":
                continue

            # we cannot ignore removing a "value", because "valueFrom"
            # cannot co-exist with a "value". check for that in env
            if op["path"].endswith("/value") and "/env/" in op["path"]:
                vf_path = re.sub(r'/value$', '/valueFrom', op["path"])
                fitting_ops = [o for o in diff
                               if ("add", vf_path) == (o["op"], o["path"])]
                if 0 < len(fitting_ops) < 2:
                    diff.append(op)

        return diff

    def _apply_delta(self, api, old_item, new_item):
        diff = self._diff(old_item, new_item)
        if diff:
            metadata_name = new_item['metadata']['name']
            if not old_item:
                action = 'create'
                args = [self.namespace, new_item]
            else:
                action = 'patch'
                args = [metadata_name, self.namespace, diff]

            underscored = _under_score(new_item["kind"])

            if self.dry_run:
                LOG.info("{}: {}/{}".format(
                    action.title(), underscored, metadata_name))
                for line in json.dumps(
                        new_item, sort_keys=True,
                        indent=2, separators=(',', ': ')).splitlines():
                    LOG.debug(line)
            else:
                LOG.debug("{}: {}/{}".format(
                    action.title(), underscored, metadata_name))
                try:
                    for line in diff:
                        LOG.debug(line)
                except TypeError:
                    pass
                method = getattr(api, '{}_namespaced_{}'.format(
                    action, underscored))

                method(*args)

    def get_api(self, api_version):
        api = [p.capitalize() for p in api_version.split('/', 1)]

        if len(api) == 1:
            api.insert(0, 'Core')

        return getattr(client, '{}{}Api'.format(api[0], api[1]), None)()

    @staticmethod
    def get_method(api, *items):
        return getattr(api, '_'.join(items))

    def apply(self):
        retry_list = []
        for (api_version, kind, name), target in six.iteritems(self.items):
            api = self.get_api(api_version)
            current = None
            try:
                reader = self.get_method(
                    api, 'read', 'namespaced', _under_score(kind))
                current = serialize(
                    reader(name, self.namespace, pretty=False, export=True))
            except client.rest.ApiException as e:
                if e.status == 404:
                    pass
                else:
                    six.reraise(*sys.exc_info())
            try:
                self._apply_delta(api, current, target)
            except client.rest.ApiException as e:
                if e.status == 422:
                    retry_list.append((api, current, target))
                else:
                    six.reraise(*sys.exc_info())

        for api, current, target in retry_list:
            try:
                self._apply_delta(api, current, target)
            except client.rest.ApiException as e:
                LOG.exception("Could not apply change")

        for (api_version, kind, name), action in six.iteritems(self.actions):
            if action != 'delete':
                continue

            api = self.get_api(api_version)
            underscored = _under_score(kind)
            if self.dry_run:
                LOG.info("{}: {}/{}".format(action.title(), underscored, name))
            else:
                try:
                    LOG.debug("{}: {}/{}".format(
                        action.title(), underscored, name))
                    deleter = self.get_method(
                        api, 'delete', 'namespaced', underscored)
                    deleter(name, self.namespace,
                            client.V1DeleteOptions(orphan_dependents=False))
                except client.rest.ApiException as e:
                    if e.status == 404:
                        pass
                    else:
                        six.reraise(*sys.exc_info())
