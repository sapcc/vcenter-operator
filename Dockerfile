FROM keppel.eu-de-1.cloud.sap/ccloud/ccloud-shell:20220106092408
LABEL source_repository="https://github.com/sapcc/vcenter-operator"
LABEL maintainer="Stefan Hipfel <stefan.hipfel@sap.com>"

WORKDIR /app
COPY kos_operator/ ./kos_operator/
COPY setup.py .

ARG CUSTOM_PYPI_URL
RUN apt-get update && \
    ls && \
    apt-get dist-upgrade -y && \
    apt-get install -y gcc libssl-dev libssl1.* git python3 python3-pip python3-setuptools && \
    pip3 install --upgrade wheel && \
    pip3 install --upgrade pip && \
    pip3 install --upgrade setuptools && \
    pip3 install --no-cache-dir --only-binary :all: --no-compile --extra-index-url ${CUSTOM_PYPI_URL} kubernetes-entrypoint && \
    pip3 install . && \
    apt-get purge -y gcc libssl-dev && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache

CMD ["kos-operator"]