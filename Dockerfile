# syntax=docker/dockerfile:1
FROM node:24 AS browser
WORKDIR /opt/compass-web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev --ignore-scripts --no-audit --no-fund

FROM ubuntu:26.04
LABEL org.opencontainers.image.title="MongoDB Compass Web" \
      org.opencontainers.image.description="Browser-native Compass UI with authenticated HTTP and verified DocumentDB TLS"
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       ca-certificates curl libatomic1 libstdc++6 nginx openssl python3 tini \
    && install -d /opt/certs \
    && curl --fail --show-error --location --retry 3 \
       https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
       --output /opt/certs/global-bundle.pem \
    && openssl crl2pkcs7 -nocrl -certfile /opt/certs/global-bundle.pem -out /dev/null \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /bin/bash compass \
    && install -d -o compass -g compass /home/compass/.config
COPY --from=browser /usr/local/bin/node /usr/local/bin/node
COPY --from=browser /usr/local/LICENSE /usr/share/doc/nodejs/LICENSE
COPY --from=browser /opt/compass-web /opt/compass-web
COPY scripts/prepare_web.py /tmp/prepare_web.py
RUN python3 /tmp/prepare_web.py /opt/compass-web/node_modules/compass-web/dist/server.js \
    && rm /tmp/prepare_web.py
COPY --chown=root:root app/ /opt/compass-container/
USER compass
ENV HOME=/home/compass XDG_CONFIG_HOME=/home/compass/.config \
    NODE_ENV=production PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /home/compass
EXPOSE 6080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python3", "/opt/compass-container/healthcheck.py"]
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/compass-container/server.py"]
