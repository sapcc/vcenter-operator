FROM python:slim as wheels

RUN apt-get update && apt-get install -y gcc libssl-dev libssl1.1
ADD requirements.txt /tmp
RUN pip wheel -w /wheels -r /tmp/requirements.txt

FROM python:slim
COPY --from=wheels /wheels /wheels
RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app
ADD . /usr/src/app
RUN export PBR_VERSION=`grep '^version *= *.*$' setup.cfg | cut -d'=' -f2 | tr -d '[:space:]'` && \
    pip install --no-index --find-links /wheels -e /usr/src/app

ENTRYPOINT [ "kos-operator" ]
