FROM keppel.eu-de-1.cloud.sap/ccloud-dockerhub-mirror/library/python:slim as wheels

RUN apt-get update && apt-get install -y gcc libssl-dev libssl1.1
ADD requirements.txt /tmp
RUN pip wheel -w /wheels -r /tmp/requirements.txt

FROM keppel.eu-de-1.cloud.sap/ccloud-dockerhub-mirror/library/python:slim
LABEL source_repository="https://github.com/sapcc/vcenter-operator"
LABEL maintainer="Stefan Hipfel <stefan.hipfel@sap.com>"

COPY --from=wheels /wheels /wheels
RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app
ADD . /usr/src/app
RUN export PBR_VERSION=`grep '^version *= *.*$' setup.cfg | cut -d'=' -f2 | tr -d '[:space:]'` && \
    pip install --no-index --find-links /wheels -e /usr/src/app

RUN  apt-get update && apt-get install -y curl \
    && curl -Lo /bin/dumb-init https://github.com/Yelp/dumb-init/releases/download/v1.2.2/dumb-init_1.2.2_amd64 \
	&& chmod +x /bin/dumb-init \
	&& dumb-init -V

ENTRYPOINT ["dumb-init", "--"]
CMD [ "kos-operator" ]
