from setuptools import setup, find_packages

setup(
    name='kos_operator',
    version='1.0.0',
    packages=find_packages(include=['kos_operator', 'kos_operator.*']),
    install_requires=[
        'pyOpenSSL==22.0.0',
        'openstacksdk>=0.19.0,<0.49.0',
        'python-openstackclient==5.0.0',
        'python-ironicclient',
        'attrs',
        'scrypt==0.8.17',
        'jinja2==3.0.3',
        'kubernetes~=26.1',
        'sentry_sdk==1.5.6',
        'dumb-init',
    ],
    url='http://www.github.com/sapcc/vcenter-operator',
    license='',
    author='SAP SE',
    description='Seeder CCloud',
    entry_points = {
        "console_scripts": [
            'kos-operator = kos_operator.cmd:main',
        ]
    },
)