import logging
from collections import defaultdict

import attr
from dns import tsigkeyring
from dns.query import xfr
from dns.rdatatype import AAAA, AXFR, CNAME, SOA, A
from kubernetes import client

LOG = logging.getLogger(__name__)
KEYALGORITHM = "hmac-sha256"  # If that doesn't work try: dns.tsig.default_algorithm


@attr.s
class _Callbacks:
    callbacks = attr.ib(default=attr.Factory(list))
    items = attr.ib(default=attr.Factory(set))
    accumulator = attr.ib(default=attr.Factory(set))


class DnsDiscovery:
    def __init__(self, domain, global_options):
        self._patterns = defaultdict(_Callbacks)

        self.domain = domain
        self.serial = None
        self.rdtype = AXFR
        self.keyname = 'tsig-key'

        self.keyring = None
        rndc_key = global_options.get('tsig_key', None)
        if rndc_key:
            self.keyring = tsigkeyring.from_text({self.keyname: rndc_key})

        self.namespace = global_options['namespace']
        self.cluster_internal = global_options['incluster']
        self.ip = global_options.get('dns_ip', None)
        self.port = int(global_options.get('dns_port', 53))
        if not self.ip:
            self._discover_dns()

    def register(self, pattern, callback):
        self._patterns[pattern].callbacks.append(callback)

    def _discover_dns(self):
        for item in client.CoreV1Api().list_namespaced_service(
                namespace=self.namespace,
                label_selector='component=mdns,type=backend').items:
            spec = item.spec
            for port in spec.ports:
                if self.cluster_internal:
                    self.ip = spec.cluster_ip
                    self.port = port.target_port
                    return
                elif spec.external_i_ps:
                    self.ip = spec.external_i_ps[0]
                    self.port = port.port
                    return

    def remote_soa_serial(self):
        try:
            # returns an iterator, that's evaluated lazily
            messages = xfr(self.ip, self.domain, port=self.port,
                           use_udp=False, rdtype=SOA, keyname=self.keyname,
                           keyring=self.keyring,
                           keyalgorithm=KEYALGORITHM)
            for message in messages:
                for answer in message.answer:
                    if answer.rdtype == SOA:
                        return answer[0].serial
        except (OSError, EOFError):
            LOG.exception('Handled an exception on retrieving the new SOA '
                          'serial gracefully.')

        return None

    def discover(self):
        new_serial = self.remote_soa_serial()

        if not new_serial:
            LOG.warning("Could not fetch SOA serial")
            return

        if self.serial and self.serial == new_serial:
            LOG.debug("No change of SOA serial")
            return

        for item in self._patterns.values():
            item.accumulator = set()

        for message in xfr(self.ip, self.domain, port=self.port,
                           use_udp=False, rdtype=self.rdtype,
                           keyname=self.keyname, keyring=self.keyring,
                           keyalgorithm=KEYALGORITHM):
            for answer in message.answer:
                if answer.rdtype in [A, AAAA, CNAME] and answer.name:
                    for pattern, item in self._patterns.items():
                        if pattern.match(answer.name.labels[0]):
                            item.accumulator.add(str(answer.name))

        for item in self._patterns.values():
            LOG.debug(f"{new_serial}: {item.accumulator}")
            item.accumulator.difference_update(item.items)
            gone = item.items.difference(item.accumulator)
            for callback in item.callbacks:
                callback(item.accumulator, gone)

            item.items.update(item.accumulator)

        self.serial = new_serial
