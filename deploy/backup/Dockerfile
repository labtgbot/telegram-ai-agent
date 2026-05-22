# Minimal backup runner image.
#
# Bundles:
#   * postgresql-client    (pg_dump / pg_restore / psql)
#   * redis cli            (redis-cli)
#   * awscli v2            (S3 + KMS)
#   * curl, jq, bash       (notifications, basic plumbing)
#   * the scripts in /opt/tgai/backup
#
# Built and pushed alongside the application images. The Helm chart
# references `backup.image.repository / backup.image.tag`; the docker-compose
# fallback references this Dockerfile directly via `build:`.

FROM alpine:3.20

ARG SUPERCRONIC_VERSION=v0.2.33

RUN apk add --no-cache \
        bash \
        ca-certificates \
        coreutils \
        curl \
        jq \
        postgresql15-client \
        redis \
        tzdata \
        py3-pip \
        python3 \
    && pip install --break-system-packages --no-cache-dir "awscli==1.34.27" \
    && curl -fsSL -o /usr/local/bin/supercronic \
        "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && chmod +x /usr/local/bin/supercronic \
    && rm -rf /root/.cache

WORKDIR /opt/tgai/backup
COPY scripts/ /opt/tgai/backup/
RUN chmod +x /opt/tgai/backup/*.sh /opt/tgai/backup/lib/*.sh

ENV PATH=/opt/tgai/backup:$PATH
USER nobody

ENTRYPOINT ["/bin/bash"]
CMD ["-c", "echo 'use a specific script: postgres-backup.sh / redis-backup.sh / media-sync.sh / verify-backup.sh'"]
