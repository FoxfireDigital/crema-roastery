FROM golang:1.27.3-alpine3.24@sha256:d200d2dd76b03a99b52651fd1325aff7dcd35422c35c01bac56571b0507f3deb AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2
WORKDIR /src
COPY proxy/go.mod proxy/go.sum ./
COPY proxy/main.go ./
COPY go_notices.go /tools/go_notices.go
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go mod download && go build -mod=readonly -p=2 -trimpath -ldflags="-s -w" -o /out/caddy . \
    && go run /tools/go_notices.go /out/caddy /out/metadata

FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS trust
RUN python -c "import subprocess,json,hashlib; from pathlib import Path; p=Path('/etc/ssl/certs/ca-certificates.crt'); package=subprocess.check_output(['dpkg-query','-W','-f=\u0024{Version}', 'ca-certificates'],text=True); Path('/trust.json').write_text(json.dumps({'name':'Debian ca-certificates','version':package,'bundleSHA256':hashlib.sha256(p.read_bytes()).hexdigest()})+'\\n')"

FROM scratch
ARG CREMA_VERSION=development
ARG CREMA_REVISION=unknown
LABEL org.opencontainers.image.title="Crema proxy" \
      org.opencontainers.image.version=$CREMA_VERSION \
      org.opencontainers.image.revision=$CREMA_REVISION
ENV XDG_CONFIG_HOME=/config XDG_DATA_HOME=/data HOME=/root
COPY --from=build /out/caddy /usr/bin/caddy
COPY --from=build /out/metadata/ /usr/share/crema-proxy/
COPY --from=trust /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=trust /usr/share/doc/ca-certificates/copyright /usr/share/crema-proxy/notices/ca-certificates/copyright
COPY --from=trust /usr/share/common-licenses/ /usr/share/crema-proxy/notices/common-licenses/
COPY --from=trust /trust.json /usr/share/crema-proxy/trust.json
COPY LICENSE /usr/share/crema-proxy/LICENSE
# Retain the upstream proxy's UID for existing certificate-volume compatibility.
# Compose restricts capabilities, writes and network exposure separately.
USER 0:0
EXPOSE 80 443
ENTRYPOINT ["/usr/bin/caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
