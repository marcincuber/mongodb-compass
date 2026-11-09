FROM ubuntu:26.04

ARG TARGETARCH
ARG COMPASS_VERSION=1.53.2
ARG COMPASS_SHA256=bb2d5a9145e5efbde1c96450755a53cfa6bfc38d33230439728b6449ad0967f5

LABEL org.opencontainers.image.title="MongoDB Compass" \
      org.opencontainers.image.description="MongoDB Compass desktop with browser access through noVNC" \
      org.opencontainers.image.version="${COMPASS_VERSION}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN test "${TARGETARCH}" = amd64 || { echo 'Compass requires --platform linux/amd64' >&2; exit 1; }
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       ca-certificates curl dbus-x11 fonts-dejavu-core nginx novnc openbox python3 \
       tini websockify x11-utils x11vnc xvfb \
       libasound2t64 libgbm1 libsecret-1-0 \
    && curl --fail --show-error --location --retry 3 \
       "https://github.com/mongodb-js/compass/releases/download/v${COMPASS_VERSION}/mongodb-compass_${COMPASS_VERSION}_amd64.deb" \
       --output /tmp/compass.deb \
    && echo "${COMPASS_SHA256}  /tmp/compass.deb" | sha256sum --check --strict \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends /tmp/compass.deb \
    && install -d /opt/certs \
    && curl --fail --show-error --location --retry 3 \
       https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
       --output /opt/certs/global-bundle.pem \
    && openssl crl2pkcs7 -nocrl -certfile /opt/certs/global-bundle.pem -out /dev/null \
    && rm -rf /var/lib/apt/lists/* /tmp/compass.deb \
    && useradd --create-home --uid 10001 --shell /bin/bash compass \
    && install -d -o compass -g compass /home/compass/.config

COPY --chown=root:root app/ /opt/compass-container/
USER compass
ENV HOME=/home/compass DISPLAY=:99 \
    XDG_CONFIG_HOME=/home/compass/.config \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /home/compass
EXPOSE 6080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python3", "/opt/compass-container/healthcheck.py"]
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/compass-container/desktop.py"]
