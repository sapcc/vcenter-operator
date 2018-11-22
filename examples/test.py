import requests
import json
import logging

from openstack import connection
from os import getenv
from kubernetes import config as k8s_config
from kubernetes import client as k8s

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)-15s %(process)d %(name)s [%(levelname)s] %(message)s')
logging.getLogger('kubernetes').setLevel(logging.WARNING)
logging.getLogger('kos_operator').setLevel(logging.DEBUG)
logging.getLogger('__main__').setLevel(logging.DEBUG)

# The pyton sdk only looks for KUBECONFIG=/Users/d063079/.kube/config
# You can change the environment variable to point it to another file
k8s_config.load_kube_config()
_, context = k8s_config.list_kube_config_contexts()
region = context['context']['cluster']
domain = 'cc.{}.cloud.sap'.format(region).strip()
namespace = 'monsoon3'
LOG = logging.getLogger(__name__)

os = connection.Connection(auth_url=getenv("OS_AUTH_URL"),
                           project_name=getenv("OS_PROJECT_NAME"),
                           project_domain_name=getenv("OS_PROJECT_DOMAIN_NAME"),
                           username=getenv("OS_USERNAME"),
                           user_domain_name=getenv("OS_USER_DOMAIN_NAME"),
                           password=getenv("OS_PASSWORD"))
