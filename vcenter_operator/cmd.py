import argparse
import logging
import os
import re
import sys
from time import sleep

import six
from kubernetes import config as k8s_config

# Import discovery before configurator as there is some monkeypatching going on
from .discovery import DnsDiscovery
from .configurator import Configurator

LOG = logging.getLogger(__name__)


def _build_arg_parser():
    args = argparse.ArgumentParser()
    args.add_argument('--dry-run', action='store_true', default=False)
    return args


def main():
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
        region = context['context']['cluster']
        domain = 'cc.{}.cloud.sap'.format(region)
        global_options['own_namespace'] = 'kube-system'
        global_options['incluster'] = False
    except IOError:
        if not 'KUBERNETES_SERVICE_HOST' in os.environ:
            os.environ['KUBERNETES_SERVICE_HOST'] = 'kubernetes.default'
        k8s_config.load_incluster_config()
        global_options['incluster'] = True
        with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace',
                  'r') as f:
            global_options['own_namespace'] = f.read()
        with open('/etc/resolv.conf', 'r') as f:
            for l in f:
                if re.match('^search\s+', l):
                    _, domain = l.rsplit(' ', 1)

    if 'SERVICE_DOMAIN' in os.environ:
        domain = os.environ['SERVICE_DOMAIN']

    configurator = Configurator(domain, global_options)
    configurator.poll_config()
    discovery = DnsDiscovery(domain, configurator.global_options)
    discovery.register(re.compile(six.b('\Avc-[a-z]+-\d+\Z')), configurator)

    while True:
        discovery.discover()
        configurator.poll()
        sleep(10)
