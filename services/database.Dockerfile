FROM golang:1.27.3-alpine3.24@sha256:d200d2dd76b03a99b52651fd1325aff7dcd35422c35c01bac56571b0507f3deb AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2
WORKDIR /src
ADD --checksum=sha256:207a2045e890d3ca3326027c5f585733085960b401a49dbc00e3bb628c054cf8 https://codeload.github.com/tianon/gosu/tar.gz/refs/tags/1.20 /source/gosu-1.20.tar.gz
RUN tar -xzf /source/gosu-1.20.tar.gz --strip-components=1 -C /src
COPY gosu/go.mod gosu/go.sum ./
COPY go_notices.go /tools/go_notices.go
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go mod download && go build -mod=readonly -p=2 -trimpath -ldflags="-s -w" -o /out/gosu . \
    && go run /tools/go_notices.go /out/gosu /out/metadata \
    && cp LICENSE /out/metadata/LICENSE

FROM postgres:16-bookworm@sha256:e8a07d2c7579b038938cdba6c539e580e5001caf9ea203d397b5cc83e76bd938
ARG CREMA_VERSION=development
ARG CREMA_REVISION=unknown
ARG APT_VERSION=2.6.2
ARG TZDATA_VERSION=2026f-0+deb12u1
LABEL org.opencontainers.image.title="Crema database" \
      org.opencontainers.image.version=$CREMA_VERSION \
      org.opencontainers.image.revision=$CREMA_REVISION
COPY --from=build /out/gosu /usr/local/bin/gosu
COPY --from=build /out/metadata/ /usr/share/crema-database/
COPY --from=build /source/gosu-1.20.tar.gz /usr/share/crema-database/sources/gosu-1.20.tar.gz
RUN chmod 0755 /usr/local/bin/gosu && chmod 0444 /usr/share/crema-database/sources/gosu-1.20.tar.gz \
    && apt-get -o Acquire::Retries=0 update && apt-get -o Acquire::Retries=0 install --yes --no-install-recommends apt=${APT_VERSION} libapt-pkg6.0=${APT_VERSION} tzdata=${TZDATA_VERSION} \
    && rm -f /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem \
    && rm -rf /var/lib/apt/lists/*
