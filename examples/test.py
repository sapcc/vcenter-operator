from openstack import connection
from os import getenv
from json import dumps

os = connection.Connection(auth_url=getenv("OS_AUTH_URL"),
                           project_name=getenv("OS_PROJECT_NAME"),
                           project_domain_name=getenv("OS_PROJECT_DOMAIN_NAME"),
                           username=getenv("OS_USERNAME"),
                           user_domain_name=getenv("OS_USER_DOMAIN_NAME"),
                           password=getenv("OS_PASSWORD"))
