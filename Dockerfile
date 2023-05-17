# syntax = docker/dockerfile:1.2
ARG BASE=keppel.eu-de-1.cloud.sap/ccloud-dockerhub-mirror/library/python:3.10-slim
FROM $BASE
LABEL source_repository="https://github.com/sapcc/vcenter-operator"

ENV SRC_DIR=/usr/src/vcenter-operator
ENV PIP_CACHE_DIR=/var/cache/pip
RUN mkdir -p $PIP_CACHE_DIR $SRC_DIR

WORKDIR $SRC_DIR
ADD . $SRC_DIR

RUN --mount=type=cache,target=${PIP_CACHE_DIR},sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    ./build.sh
