import json
import logging
import six

from collections import deque
from socket import error as socket_error
from kubernetes import client

from .masterpassword import MasterPassword
from .phelm import DeploymentState
from .crds import CRDS

LOG = logging.getLogger(__name__)


class Configurator(object):
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
            for name, item in crd.poll(self.global_options):
                  self._items[name] = item

    def poll(self):
        self.poll_config()

        state = DeploymentState(
            namespace=self.global_options['namespace'],
            dry_run=(self.global_options.get('dry_run', 'False') == 'True'))
        self.states.append(state)

        for name, item in six.iteritems(self._items):
            missing = [r for r in item.requirements if r not in self._items]
            if not missing:
                item.execute(state)
            else:
                LOG.warning("Missing requirements for %s: %s", name, missing)

        if len(self.states) > 1:
            last = self.states.popleft()
            delta = last.delta(self.states[-1])
            delta.apply()
        else:
            self.states[-1].apply()
