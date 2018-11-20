import argparse
import logging
import os
import re
import sys
from time import sleep

import six
from kubernetes import config as k8s_config

from .configurator import Configurator

log = logging.getLogger(__name__)


def _build_arg_parser():
    args = argparse.ArgumentParser()
    args.add_argument('--dry-run', action='store_true', default=False)
    return args


def main():
    args = _build_arg_parser().parse_args(sys.argv[1:])
    global_options = {'dry_run': str(args.dry_run)}

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)-15s %(process)d %(levelname)s %(message)s')
    logging.getLogger('kubernetes').setLevel(logging.WARNING)
    logging.getLogger('kos_operator').setLevel(logging.DEBUG)

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


    global_options['namespace'] = 'monsoon3'
    global_options['domain'] = domain.strip()

    configurator = Configurator(domain, global_options)
    configurator.poll_config()

    while True:
        configurator.poll()
        sleep(10)

if __name__ == "__main__":
    main()
