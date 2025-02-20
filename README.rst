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
