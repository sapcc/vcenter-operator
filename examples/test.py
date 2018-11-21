from openstack import connection
import requests
import json
from os import getenv
from kubernetes import config as k8s_config
from kubernetes import client as k8s

# The pyton sdk only looks for KUBECONFIG=/Users/d063079/.kube/config
# You can change the environment variable to point it to another file
k8s_config.load_kube_config()
_, context = k8s_config.list_kube_config_contexts()
region = context['context']['cluster']
domain = 'cc.{}.cloud.sap'.format(region).strip()
namespace = 'monsoon3'

os = connection.Connection(auth_url=getenv("OS_AUTH_URL"),
                           project_name=getenv("OS_PROJECT_NAME"),
                           project_domain_name=getenv("OS_PROJECT_DOMAIN_NAME"),
                           username=getenv("OS_USERNAME"),
                           user_domain_name=getenv("OS_USER_DOMAIN_NAME"),
                           password=getenv("OS_PASSWORD"))
