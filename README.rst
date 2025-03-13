VCenter Operator
=============

The `vcenter-operator` automatically configures and deploys cinder and nova-compute nodes corresponding to the discovered vCenters and clusters.
It follows the convention over configuration principle to keep the configuration to a minimum. It relies heavily on other k8s ConfigMaps and Secrets being deployed by `helm-charts/openstack <https://github.com/sapcc/helm-charts/tree/master/openstack>`_  and should be best deployed with it.
The helm-chart for the `vcenter-operator` can be found `here <https://github.com/sapcc/helm-charts/tree/master/openstack/vcenter-operator>`_.


Brief Overview
-------------------
#. Initially retrieving information about the k8s cluster it runs on
#. Polling the vCenters username and password from `vcenter-operator` k8s Secret
#. Discovering vCenters via DNS (change detection via serials)
#. Reading the VCenterTemplate Custom Resources from k8s to retrieve all/update templates that need rendering
#. Re-/connecting to each vCenter and collecting information (ESXI cluster, storage, network)
    #. Rendering the collected information via jinja2 templates
    #. Creating a delta if old state exists
    #. Finally deleted objects get removed, new or modified objects get applied in k8s cluster (server-side-apply)
    
#. Wait 10 seconds and start again from step 3.


Configuration
-------------------

Some basic configuration is however necessary. The `vcenter-operator` has to be deployed in a way that it allows it to deploy and modify resources within the configured target namespace.
The following values are required to be stored in a k8s Secret named `vcenter-operator` in the same namespace as the running pod, and expects the following values:


namespace
    The namespace to deploy into

username
    The username to use to log on the vCenter

password
    A password used as a seed for the `master-password algorithm <https://masterpassword.app/masterpassword-algorithm.pdf>`_ to generate long-form passwords specific for each vCenter discovered.

tsig_key
    A transaction signature key used to authenticate the communication with the DNS-service and retrieve DNS-messages

manage_service_user_passwords
    A boolean value to indicate if the operator should manage the service-user passwords in the vCenter.
    If set to `true`, the following keys will be added to the config as well.

role_id
    UUID of the role used to authenticate with Vault

secret_id
    UUID of the secret used to authenticate with Vault

ad_ttu_username
    The username used to login to the vCenter via SSO, in the form of `name@domain`

ad_ttu_password
    The password used to login to the vCenter via SSO

active_directory
    The name of the Active Directory used to login to the vCenter via SSO

vault_url
    The url of the Vault service

vault_check_interval
    The interval in seconds to check Vault for new versions of secrets

mount_point_read
    The name of the part of the Vault service where secrets are read from
    Secrets get replicated to this mount point from the `mount_point_write`

mount_point_write
    The name of the part of the Vault service to write secrets to
    Secrets get replicated from this mount point to the `mount_point_read`

max_time_not_seen
    The maximum time in seconds that a service-user version was not seen as label at any Pod
    Makes sure only service-users get deleted that are not used anymore

password_length
    The length of the generated password for the service-user

password_digits
    The number of digits in the generated password for the service-user

password_symbols
    The number of symbols in the generated password for the service-user


Conventions
-------------------

The `vcenter-operator` relies on the following conventions:

- The operator relies on having dns as a kubernetes service with the labels `component=mdns,type=backend`, and polls the DNS behind it.

- When the domain can not be obtained via the kube config, it polls the last search domain of the `resolv.conf`.

- Within that domain, the vCenter is expected to match `vc-[a-z]+-[0-9]+`.

- The operator expects to be able to log on with username and the long form password derived by the given user and password for the fully-qualified domain name of the vCenter.

- Within the vCenter, the name of the VSphere datacenter will be used as the availability-zone name (in lower-case) for each entity child.

- Within a Datacenter, clusters prefixed with `production` will be used as compute nodes. The name of the compute-host will be the `nova-compute-<suffix>`, where `suffix` is whatever stands after `production` in the cluster-name.

- Within that cluster, the nova storage will be derived by looking for mounted storage prefixed by `eph`. The longest common prefix will be used as a search pattern for the storage of the compute node.

- The first Port-group within that cluster prefixed with `br-` will be used for the vm networking, and the suffix determines the physical name of the network.

- A cluster prefixed with `storage` will cause the creation of a cinder nodes with the name `cinder-volume-vmware-<suffix>`. This is only provisional and should be replaced by one per datacenter.


Testing
-------------------

The `vcenter-operator` can be tested as follows:

- Create a venv and install the dependencies in editable mode `pip install -e .`
- Setup your environment to have access to the desired k8s cluster to test on
- Run the operator in dry run mode `vcenter-operator --dry-run`
- This will log the rendered templates and also test the apply functionality in dry-run mode

Unit-tests exist for the service-user management. They can be run with: `pip install -r test-requirements.txt` and `pytest tests`


Clean up
-------------------
When removing a `VCenterServiceUser` CR there is no clean up of the service-user in the vCenter and in Vault.
This needs to be done **manually**.


Good to know
-------------------
`VCenterServiceUser` CRs should not have the same template username as this causes issues with the service-user management.
This will be checked by the operator and it will go into error state not rendering the template with a potentially wrong username and password.
This behavior should get solved by fixing the newly created `VCSU` CRs to have an unique username template.
Yet if the service-user is not cleaned up correctly after the CR is removed, it will be possible to create such a state.
If a service-user should be created that already exists or starts with the same prefix in the vCenter (due to a previous CR that did not got cleaned up correctly), the creation of the user will fail with an error message and nothing gets rendered.

If a service-user needs to be rotated manually for some reason, it is important to rotate the secret in the write mount and not directly in the read mount.

The operator uses an ad-user to connect to the vCenters. This user can expire and then the operator will not be able to connect to the vCenters anymore. A new ad-user needs to be created and updated in the secret.
Ad-users can currently not be rotated.
