import logging
import re
import requests
import urllib3

LOG = logging.getLogger(__name__)


class NotAuthorizedException(Exception):
    pass


class ObjectAlreadyExistsException(Exception):
    pass


class ObjectDoesNotExistException(Exception):
    pass


class ConnectionError(Exception):
    pass

class NSXTSkippedError(Exception):
    pass

class NsxtLoginHelper():
    def __init__(self, dry_run=False, user=None, password=None, bb=None, region=None, verify_ssl=False):
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
                raise ValueError('"{}" is not a valid building block'.format(bb))

            bb = int(m.group('num'))

        if leading_zero:
            return 'bb{:03}'.format(bb)
        else:
            return 'bb{}'.format(bb)

    def gen_fullpath(self, subpath):
        url = f"https://nsx-ctl-{self.bb}.cc.{self.region}.cloud.sap"
        return f"{url}/{subpath}"

    def connect(self):
        self._create_session()
        try:
            url = self.gen_fullpath("api/session/create")
            r = self.session.post(url, data={'j_username': self.user, 'j_password': self.password}, verify=False)
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError("Could not connect to nsx-t: {}".format(e))

        if r.status_code != 200:
            raise NotAuthorizedException("Authentication failure to {} with user {}".format(self.bb, self.user))

        self.session.headers['X-XSRF-TOKEN'] = r.headers['X-XSRF-TOKEN']

    def is_logged_in(self):
        if self.session is None:
            return False

        # this would return a 404 if the session is valid, 403 otherwise
        r = requests.get(self.gen_fullpath("api"))
        return r.status_code != 403

    def get(self, url, params=None):
        if self.is_logged_in:
            self.connect()
        res = self.session.get(url, params=params)

        if res.status_code == 403:
            raise NotAuthorizedException("Authentication failure to {} with user {}".format(self.bb, self.user))

        if res.status_code == 404:
            raise ObjectDoesNotExistException("Object does not exist.")

        res = res.json()
        if "results" in res.keys():
            res = res["results"]

        return res

    def delete(self, url, params=None):
        if self.is_logged_in:
            self.connect()
        res = self.session.delete(url)

        if res.status_code == 403:
            raise NotAuthorizedException("Authentication failure to {} with user {}".format(self.bb, self.user))

        res.raise_for_status()

        return res

    def post(self, url, data=None, params=None):
        if self.is_logged_in:
            self.connect()
        res = self.session.post(url, json=data, params=params)
        if res.status_code == 403:
            raise NotAuthorizedException("Authentication failure to {} with user {}".format(self.bb, self.user))

        # User already exists
        if res.status_code == 409:
            raise ObjectAlreadyExistsException("Object already exists")

        res.raise_for_status()

        return res

    def put(self, url, data=None, params=None):
        if self.is_logged_in:
            self.connect()
        res = self.session.put(url, json=data, params=params)
        if res.status_code == 403:
            raise NotAuthorizedException("Authentication failure to {} with user {}".format(self.bb, self.user))

        # User already exists
        if res.status_code == 409:
            raise ObjectAlreadyExistsException("Object already exists")

        res.raise_for_status()

        return res


class User():
    def __init__(self, name, id, roles, role_mapping_id, revision):
        self._name = name
        self._id = id
        self._roles = roles
        self._role_mapping_id = role_mapping_id
        self._revision = revision

    @property
    def rolemappingid(self):
        return self._role_mapping_id

    @property
    def revision(self):
        return self._revision

    @property
    def name(self):
        return self._name

    @property
    def id(self):
        return self._id

    @property
    def roles(self):
        return self._roles

    @roles.setter
    def roles(self, roles):
        self._roles = roles

    @id.setter
    def id(self, id):
        self._id = id

    @name.setter
    def name(self, name):
        self._name = name

    def __repr__(self):
        return f"{self.id}: {self.name}: {self.roles}"

    def has_all_roles(self, expected_roles):
        if type(expected_roles) is not list:
            expected_roles = [expected_roles]
        expected_roles = set(expected_roles)
        roles = set(self._roles)

        # User is missing a role
        if expected_roles - roles:
            return False
        return True


class NsxtUserAPIHelper(NsxtLoginHelper):
    def __init__(self, user, password, bb, region):
        super(NsxtUserAPIHelper, self).__init__(dry_run=False, user=user, password=password, bb=bb, region=region)

    def get_user_role_mapping(self, user_group_name):
        "Fetch role mapping for the given username or group name"
        path = "api/v1/aaa/role-bindings"
        params = {"name": user_group_name}

        user_role_mappping = self.get(self.gen_fullpath(path), params)

        if len(user_role_mappping) > 1 or len(user_role_mappping) == 0:
            # ToDo: return an error
            return []

        user_role_mappping = user_role_mappping[0]
        roles = [role["role"] for role in user_role_mappping.get('roles', [])]
        name = user_role_mappping["name"]
        id = user_role_mappping["user_id"]
        role_mapping_id = user_role_mappping["id"]
        revision = user_role_mappping["_revision"]

        u = User(name=name, id=id, roles=roles,
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
            return users

        return [u["username"] for u in users if u["username"].startswith(prefix)]

    def check_users_in_group(self, user, groups):
        if isinstance(user, str):
            curr_user = self.get_user_role_mapping(user)
        else:
            curr_user = user
        return curr_user.has_all_roles(groups)

    def get_role(self, role_name):
        path = "/api/v1/aaa/roles/{}".format(role_name)
        return self.get(self.gen_fullpath(path))

    def list_roles(self):
        path = "api/v1/aaa/roles"
        return self.get(self.gen_fullpath(path))

    def add_user_to_group(self, username, groupname):
        user = self.get_user_role_mapping(username)

        if self.check_users_in_group(user, groupname):
            LOG.info("User {} already has role {}".format(username, groupname))
            return True

        path =  f"api/v1/aaa/role-bindings/{user.rolemappingid}"
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
        return True

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
        except ObjectAlreadyExistsException:
            LOG.debug("User {} already exists".format(username))
        return True

    def delete_service_user(self, username):
        path = "api/v1/node/users/{}"
        user = self.get_user_role_mapping(username)
        self.delete(self.gen_fullpath(path.format(user.id)))
