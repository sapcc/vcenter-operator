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
            r = requests.post(url, data={'j_username': self.user, 'j_password': self.password}, verify=False)
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

    def get(self, url):
        if self.is_logged_in:
            self.connect()
        res = self.session.get(url)

        if res.status_code == 403:
            raise NotAuthorizedException("Authentication failure to {} with user {}".format(self.bb, self.user))

        if res.status_code != requests.codes.ok:
            return res

        return res

    def post(self):
        if self.is_logged_in:
            self.connect()


class NsxtUserAPIHelper(NsxtLoginHelper):
    def __init__(self, user, password, bb, region):
        super(NsxtUserAPIHelper, self).__init__(dry_run=False, user=user, password=password, bb=bb, region=region)

    def list_users(self, exclude=None):
        path = "api/v1/node/users"
        path = "global-manager/api/v1/global-infra/dns-security-profiles"
        users = self.get(self.gen_fullpath(path))
        for u in users:
            print(f"{u}")

    def check_users_in_group(self, user, group):
        pass

    def create_service_user(self, user, groups):
        pass

    def add_user_to_group(self, user, group):
        pass

    def delete_service_user(self):
        pass


if __name__ == '__main__':
    user = os.getenv('NSXT_USER')
    password = os.getenv('NSXT_PW')
    bb = os.getenv('NSXT_BB')
    region = os.getenv('NSXT_REGION')

    print(f"connecting to {bb} in region {region} with {user}")
    user_api = NsxtUserAPIHelper(user, password, bb, region)
    user_api.list_users()
