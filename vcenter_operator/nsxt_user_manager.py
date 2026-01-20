import logging
import re

import requests
import urllib3

LOG = logging.getLogger(__name__)


class NotAuthorizedError(Exception):
    pass


class ObjectAlreadyExistsError(Exception):
    pass


class ObjectDoesNotExistError(Exception):
    pass


class ConnectionError(Exception):
    pass


class NSXTSkippedError(Exception):
    pass


class NsxtLoginHelper:
    def __init__(self, user=None, password=None, bb=None, region=None, verify_ssl=False, dry_run=False):
        self.dry_run = dry_run
        self.user = user
        self.password = password
        self.session = None
        self.region = region
        self.bb = self.parse_buildingblock(bb)

        if not verify_ssl:
            urllib3.disable_warnings()

    def _create_session(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.verify = False

    def parse_buildingblock(self, bb, leading_zero=True):
        if bb is None:
            return

        if not isinstance(bb, int):
            m = re.match(r'^b?b?(?P<num>\d+)$', bb.lower())
            if not m:
                raise ValueError(f'"{bb}" is not a valid building block')

            bb = int(m.group('num'))

        if leading_zero:
            return f'bb{bb:03}'
        else:
            return f'bb{bb}'

    def gen_fullpath(self, subpath):
        url = f"https://nsx-ctl-{self.bb}.cc.{self.region}.cloud.sap"
        return f"{url}/{subpath}"

    def connect(self):
        self._create_session()
        try:
            url = self.gen_fullpath("api/session/create")
            r = self.session.post(url, data={'j_username': self.user, 'j_password': self.password})
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Could not connect to nsx-t: {e}")

        if r.status_code != 200:
            raise NotAuthorizedError(f"Authentication failure to {self.bb} with user {self.user}")

        self.session.headers['X-XSRF-TOKEN'] = r.headers['X-XSRF-TOKEN']

    def is_logged_in(self):
        if self.session is None:
            return False

        # this would return a 404 if the session is valid, 403 otherwise
        r = requests.get(self.gen_fullpath("api"))
        return r.status_code != 403

    def get(self, url, params=None):
        if not self.is_logged_in():
            self.connect()
        res = self.session.get(url, params=params)

        if res.status_code == 403:
            raise NotAuthorizedError(f"Authentication failure to {self.bb} with user {self.user}")

        if res.status_code == 404:
            raise ObjectDoesNotExistError("Object does not exist.")

        res.raise_for_status()

        res = res.json()
        if "results" in res:
            res = res["results"]

        return res

    def delete(self, url, params=None):
        if not self.is_logged_in():
            self.connect()
        res = self.session.delete(url)

        if res.status_code == 403:
            raise NotAuthorizedError(f"Authentication failure to {self.bb} with user {self.user}")

        res.raise_for_status()

        return res

    def post(self, url, data=None, params=None):
        if self.dry_run:
            LOG.debug("Dry run, Not executing POST request")
            return True
        if not self.is_logged_in():
            self.connect()
        res = self.session.post(url, json=data, params=params)
        if res.status_code == 403:
            raise NotAuthorizedError(f"Authentication failure to {self.bb} with user {self.user}")

        if res.status_code == 409:
            raise ObjectAlreadyExistsError("Object already exists")

        res.raise_for_status()

        return res

    def put(self, url, data=None, params=None):
        if self.dry_run:
            LOG.debug("Dry run, Not executing PUT request")
            return True
        if not self.is_logged_in():
            self.connect()
        res = self.session.put(url, json=data, params=params)
        if res.status_code == 403:
            raise NotAuthorizedError(f"Authentication failure to {self.bb} with user {self.user}")

        if res.status_code == 409:
            raise ObjectAlreadyExistsError("Object already exists")

        res.raise_for_status()

        return res


class User:
    def __init__(self, name, id, roles, role_mapping_id, revision):
        self.name = name
        self.id = id
        self.roles = roles
        self.role_mapping_id = role_mapping_id
        self.revision = revision

    def __repr__(self):
        return f"{self.id}: {self.name}: {self.roles}"

    def has_all_roles(self, expected_roles):
        if isinstance(expected_roles, str):
            expected_roles = [expected_roles]
        expected_roles = set(expected_roles)
        roles = set(self.roles)

        # User is missing a role
        if expected_roles - roles:
            return False
        return True


class NsxtUserAPIHelper(NsxtLoginHelper):
    def __init__(self, user, password, bb, region, dry_run):
        super().__init__(user=user, password=password, bb=bb, region=region,
                                                verify_ssl=False, dry_run=dry_run)

    def get_user(self, username):
        "Fetch user and role mapping information for the given username"
        path = "api/v1/aaa/role-bindings"
        params = {"name": username}

        user_role_mappping = self.get(self.gen_fullpath(path), params)

        if len(user_role_mappping) > 1 or len(user_role_mappping) == 0:
            # ToDo: return an error
            return None

        user_role_mappping = user_role_mappping[0]
        roles = [role["role"] for role in user_role_mappping.get('roles', [])]
        name = user_role_mappping["name"]
        user_id = user_role_mappping["user_id"]
        role_mapping_id = user_role_mappping["id"]
        revision = user_role_mappping["_revision"]

        u = User(name=name, id=user_id, roles=roles,
                 role_mapping_id=role_mapping_id, revision=revision)
        return u

    def list_user_role_mappings(self):
        path = "policy/api/v1/aaa/role-bindings"
        return self.get(self.gen_fullpath(path))

    def list_roles(self):
        path = "api/v1/aaa/roles"
        return self.get(self.gen_fullpath(path))

    def list_users(self, prefix="nsxt"):
        path = "api/v1/node/users"

        users = self.get(self.gen_fullpath(path))

        if not prefix:
            return [u["username"] for u in users]

        return [u["username"] for u in users if u["username"].startswith(prefix)]

    def check_users_in_group(self, user, groups):
        if isinstance(user, str):
            curr_user = self.get_user(user)
        else:
            curr_user = user
        return curr_user.has_all_roles(groups)

    def get_role(self, role_name):
        path = f"api/v1/aaa/roles/{role_name}"
        return self.get(self.gen_fullpath(path))

    def add_user_to_group(self, username, groupname):
        user = self.get_user(username)

        if self.check_users_in_group(user, groupname):
            LOG.debug(f"User {username} already has role {groupname}")
            return

        path =  f"api/v1/aaa/role-bindings/{user.role_mapping_id}"
        role_mapping = {
            "_revision": user.revision,
            "name": user.name,
            "read_roles_for_paths": True,
            "type": "local_user",
            "roles_for_paths": [
                {
                    # Default path we have been using so far
                    "path": "/",
                    "roles": [
                        {
                            "role": groupname,
                        }
                    ]
                }
            ]
        }

        self.put(self.gen_fullpath(path), data=role_mapping)

    def create_service_user(self, username, password):
        path = "api/v1/node/users"

        user = {
            "full_name": username,
            "username": username,
            "password": password,
            "password_change_frequency": 0,
            "status": "ACTIVE"
        }
        params = {"action": "create_user"}
        try:
            self.post(self.gen_fullpath(path), data=user, params=params)
        except ObjectAlreadyExistsError:
            LOG.debug(f"User {username} already exists")

    def delete_service_user(self, username):
        path = "api/v1/node/users/{}"
        user = self.get_user(username)
        self.delete(self.gen_fullpath(path.format(user.id)))
