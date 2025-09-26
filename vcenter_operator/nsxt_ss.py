import os
import re
import requests
import urllib3
from ratelimit import limits, sleep_and_retry

class NotAuthorizedException(Exception):
    pass

class ConnectionError(Exception):
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

        if res.status_code != requests.codes.ok:
            return res

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
        return res

    def post(self, url, data=None, params=None):
        if self.is_logged_in:
            self.connect()
        res = self.session.post(url, json=data, params=params)
        if res.status_code == 403:
            raise NotAuthorizedException("Authentication failure to {} with user {}".format(self.bb, self.user))
        return res


class User():
    def __init__(self, name, id, roles):
        self._name = name
        self._id = id
        self._roles = roles
    
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
        expected_roles = set(expected_roles)
        roles = set(self._roles)

        #User is missing a role
        if expected_roles - roles:
            return False
        return True


class NsxtUserAPIHelper(NsxtLoginHelper):
    def __init__(self, user, password, bb, region):
        super(NsxtUserAPIHelper, self).__init__(dry_run=False, user=user, password=password, bb=bb, region=region)

    def get_user_role_mapping(self, username):
        path="api/v1/aaa/role-bindings"

        params = {"name": username}

        user_role_mappping = self.get(self.gen_fullpath(path), params)

        if len(user_role_mappping) > 1:
            #ToDo: return an error
            return

        user_role_mappping = user_role_mappping[0]
        roles = [role["role"] for role in user_role_mappping.get('roles', [])]
        u = User(name=user_role_mappping["name"], id=user_role_mappping["user_id"], roles=roles)

        return u

    def list_user_role_mappings(self, user):
        path = "policy/api/v1/aaa/role-bindings"

    def list_users(self, prefix="nsxt"):
        path = "api/v1/node/users"
        users = self.get(self.gen_fullpath(path))
        matchin_users = []
        for u in users:
            if not prefix or (prefix in u["username"]):
                matchin_users.append(u)
        return matchin_users


    def check_users_in_group(self, username, groups):
        curr_user = self.get_user_role_mapping(username)
        return curr_user.has_all_roles(groups)


    def add_user_to_group(self, user, group):
        pass

    def create_service_user(self, username, password):
        path="api/v1/node/users"

        user = {
            "full_name": username,
            "username": username,
            "password": password,
            #0 to indicate no password change is required --> Handled via this operator 
            "password_change_frequency": 0,
            "status": "ACTIVE"
        }
        params =  {"action": "create_user"}
        res = self.post(self.gen_fullpath(path), data=user, params=params)

        if res.status_code != requests.codes.ok:
            raise Exception("Could not create user {}  {}".format(username, res.text))

    def delete_service_user(self, username):
        path = "api/v1/node/users/{}"
        user = self.get_user_role_mapping(username)
        res = self.delete(self.gen_fullpath(path.format(user.id)))

        if res.status_code != requests.codes.ok:
            raise Exception("Could not create user {}  {}".format(username, res.text))


if __name__ == '__main__':
    user = os.getenv('NSXT_USER')
    password = os.getenv('NSXT_PW')
    bb = os.getenv('NSXT_BB')
    region = os.getenv('NSXT_REGION')

    print(f"connecting to {bb} in region {region} with {user}")
    user_api = NsxtUserAPIHelper(user, password, bb, region)

    try:
        user_api.create_service_user("guestuser1", "GuestUser1!!")
    except Exception as e:
        pass
    finally:
        user_api.delete_service_user("guestuser1")
