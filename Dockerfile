FROM python:slim
LABEL source_repository="https://github.com/sapcc/vcenter-operator"

RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app
ADD . /usr/src/app
RUN ./build.sh
