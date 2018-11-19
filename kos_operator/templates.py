import hashlib
import logging

from jinja2 import BaseLoader, ChoiceLoader, Environment, \
    contextfilter, TemplateNotFound
from kubernetes import client

from .masterpassword import MasterPassword

LOG = logging.getLogger(__name__)


def _ini_quote(value):
    return '"{}"'.format(_ini_escape(value).replace('"', '\\"'))


def _ini_escape(value):
    return str(value).replace('$', '$$')


def _split_string(value, separator=None):
    return value.split(separator)


@contextfilter
def _derive_password(ctx, username=None, host=None):
    username = username or ctx['username']
    host = host or ctx['host']
    mpw = MasterPassword(name=username, password=ctx['master_password'])
    return mpw.derive('long', host)


def _sha256sum(data):
    sha1 = hashlib.new('sha256')
    sha1.update(data)
    return sha1.hexdigest()


@contextfilter
def _render(ctx, template_name):
    template = ctx.environment.get_template(template_name)
    return template.render(ctx)


_SAVED_DEFAULTS = {}


def restore_defaults(env):
    global _SAVED_DEFAULTS
    for k in _SAVED_DEFAULTS:
        setattr(env, k, _SAVED_DEFAULTS[k])
    _SAVED_DEFAULTS.clear()


def store_default(env, k):
    global _SAVED_DEFAULTS
    if k in _SAVED_DEFAULTS:
        return

    _SAVED_DEFAULTS[k] = getattr(env, k)


class CustomResourceDefinitionLoader(BaseLoader):
    def __init__(self):
        self.mapping = {}

    def get_source(self, environment, template):
        if template in self.mapping:
            version, source, jinja2_options = self.mapping[template]
            restore_defaults(environment)

            for k in jinja2_options:
                if hasattr(environment, k):
                    store_default(environment, k)
                    setattr(environment, k, jinja2_options[k])

            return source, None, lambda: \
                template in self.mapping and \
                (version, source, jinja2_options) == self.mapping.get(template)
        raise TemplateNotFound(template)

    def list_templates(self):
        return sorted(self.mapping)

CRD_LOADER = CustomResourceDefinitionLoader()

env = Environment(loader=CRD_LOADER)

env.filters['ini_escape'] = _ini_escape
env.filters['ini_quote'] = _ini_quote
env.filters['quote'] = _ini_quote
env.filters['split_string'] = _split_string
env.filters['derive_password'] = _derive_password
env.filters['sha256sum'] = _sha256sum
env.filters['render'] = _render
