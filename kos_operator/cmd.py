import argparse
import logging
import os
import re
import sys
from time import sleep
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from kubernetes import config as k8s_config

from .configurator import Configurator

LOG = logging.getLogger(__name__)


def _build_arg_parser():
    args = argparse.ArgumentParser()
    args.add_argument('--dry-run', action='store_true', default=False)
    return args


def main():
    args = _build_arg_parser().parse_args(sys.argv[1:])
    global_options = {'dry_run': str(args.dry_run)}

    if 'SENTRY_DSN' in os.environ:
        dsn = os.environ['SENTRY_DSN']
        if 'verify_ssl' not in dsn:
            dsn = "%s?verify_ssl=0" % os.environ['SENTRY_DSN']

        sentry_logging = LoggingIntegration(
            level=logging.INFO,        # Capture info and above as breadcrumbs
            event_level=logging.ERROR  # Send errors as events
        )
        sentry_sdk.init(
            dsn=dsn,
            integrations=[sentry_logging]
        )

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)-15s %(process)d %(name)s [%(levelname)s] %(message)s')
    logging.getLogger('kubernetes').setLevel(logging.WARNING)
    logging.getLogger('kos_operator').setLevel(logging.DEBUG)

    try:
        k8s_config.load_kube_config()
        _, context = k8s_config.list_kube_config_contexts()
        region = context['context']['cluster']
        domain = 'cc.{}.cloud.sap'.format(region)
        global_options['own_namespace'] = 'kube-system'
        global_options['incluster'] = False
    except:
        if 'KUBERNETES_SERVICE_HOST' not in os.environ:
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
        LOG.debug('-----> exec poll <-----')
        configurator.poll()
        sleep(600)

if __name__ == "__main__":
    main()
