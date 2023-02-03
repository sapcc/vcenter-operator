import logging

from collections import deque
from kubernetes import client

from .phelm import DeploymentState
from .crds import CRDS, KosQueryExecError

LOG = logging.getLogger(__name__)


class Configurator:
    def __init__(self, domain, global_options={}):
        self.global_options = global_options.copy()
        self.password = None
        self.mpw = None
        self.domain = domain
        self.states = deque()
        self._items = dict()
        self.poll_config()

    @property
    def _client(self):
        return client

    def poll_config(self):
        self._items = dict()
        for crd in CRDS:
            for name, item in crd.poll():
                self._items[name] = item

    def _execute_item(self, results, state, name):
        if name in results:
            return results[name]

        variables = self.global_options.copy()
        item = self._items[name]
        for r in item.requirements:
            variables.update(self._execute_item(results, state, r))

        return item.execute(state, variables)

    def poll(self):
        self.poll_config()

        state = DeploymentState(
            namespace=self.global_options['namespace'],
            dry_run=(self.global_options.get('dry_run', 'False') == 'True'))
        self.states.append(state)

        results = {}

        for name, item in self._items.items():
            if not item.do_execute:
                continue
            try:
                self._execute_item(results, state, name)
            except (LookupError, KosQueryExecError) as e:
                LOG.error(
                    "Error executing kos crd: {}. Error: {}".format(name, e))
                # Lets stop the updates. Otherwise crds with the missing req or execution error get deleted!
                # e.g.: This is the case when updating openstackseeds (Delete -> Create new seed)
                return

        if len(self.states) > 1:
            last = self.states.popleft()
            delta = last.delta(self.states[-1])
            delta.apply()
        else:
            self.states[-1].apply()
