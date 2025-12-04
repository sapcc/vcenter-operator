import argparse
import logging
import os
import re
import signal
import sys
from time import sleep

from kubernetes import config as k8s_config
from pyvmomi_extended import extend_pyvmomi

from vcenter_operator.configurator import Configurator

# Import discovery before configurator as there is some monkeypatching going on
from vcenter_operator.discovery import DnsDiscovery

LOG = logging.getLogger(__name__)


def handle_term(signum, frame):
    LOG.info("terminating")
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_term)


def _build_arg_parser():
    args = argparse.ArgumentParser()
    args.add_argument('--dry-run', action='store_true', default=False)
    return args


def main():
    # Extend pyvmomi with the methods to use ssoadmin
    extend_pyvmomi()

    args = _build_arg_parser().parse_args(sys.argv[1:])
    global_options = {'dry_run': str(args.dry_run)}

    log_level = logging.INFO
    if 'LOG_LEVEL' in os.environ:
        try:
            log_level = getattr(logging, os.environ.get('LOG_LEVEL'))
        except AttributeError:
            msg = 'The configured log-level "{}" is not available.'
            raise RuntimeError(msg.format(os.environ.get('LOG_LEVEL')))
    logging.basicConfig(
        level=log_level,
        format='%(asctime)-15s %(process)d %(levelname)s %(name)s %(message)s')
    logging.getLogger('kubernetes').setLevel(logging.WARNING)
    logging.getLogger('keystoneauth').setLevel(logging.WARNING)

    try:
        k8s_config.load_kube_config()
        _, context = k8s_config.list_kube_config_contexts()
        cluster = context['context']['cluster']
        # I.e. kubectl-sync:1234:qa-de-2:1.25.6 -> qa-de-2
        m = re.search(r'[a-z]+-[a-z]+-\d', cluster)
        if not m:
            raise RuntimeError(f"Cannot derive region from cluster {cluster}")
        region = m[0]
        global_options['region'] = region
        domain = f'cc.{region}.cloud.sap'
        global_options['own_namespace'] = 'monsoon3'
        global_options['incluster'] = False
    except (OSError, k8s_config.config_exception.ConfigException):
        if 'KUBERNETES_SERVICE_HOST' not in os.environ:
            os.environ['KUBERNETES_SERVICE_HOST'] = 'kubernetes.default'
        k8s_config.load_incluster_config()
        global_options['incluster'] = True
        with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace') as f:
            global_options['own_namespace'] = f.read()
        with open('/etc/resolv.conf') as f:
            for line in f:
                if re.match(r'^search\s+', line):
                    _, domain = line.rsplit(' ', 1)
        # cc.{region}.cloud.sap
        region = domain.split('.')[1]
        global_options['region'] = region

    if 'SERVICE_DOMAIN' in os.environ:
        domain = os.environ['SERVICE_DOMAIN']

    configurator = Configurator(domain, global_options)
    configurator.poll_config()
    discovery = DnsDiscovery(domain, configurator.global_options)
    discovery.register(re.compile(br'\Avc-[a-z]+-\d+\Z'), configurator)

    while True:
        discovery.discover()
        configurator.poll()
        sleep(10)
