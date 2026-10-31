FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS driver-build
ARG LIBPQ_VERSION=15.19-0+deb12u1
WORKDIR /build
RUN apt-get update && apt-get install --yes --no-install-recommends gcc libc6-dev libpq-dev=${LIBPQ_VERSION} \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir pip==26.2.2 setuptools==83.0.0 wheel==0.48.0
# Retain the exact C extension source, including its license and build backend.
ADD --checksum=sha256:29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8 https://files.pythonhosted.org/packages/58/53/bf15aa48cd6f0ad0039b9f48681d2e76e8564d413af47b13fab50dd03555/psycopg_c-3.3.6.tar.gz /build/sources/psycopg_c-3.3.6.tar.gz
RUN python -m pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /build/wheels /build/sources/psycopg_c-3.3.6.tar.gz \
    && python -c "import json,hashlib,importlib.metadata as m,subprocess; from pathlib import Path; files=list(Path('/build').glob('*/*')); report={'format':'crema-driver-build-v1','implementation':'psycopg-c','sourceURL':'https://files.pythonhosted.org/packages/58/53/bf15aa48cd6f0ad0039b9f48681d2e76e8564d413af47b13fab50dd03555/psycopg_c-3.3.6.tar.gz','files':[{'path':str(p.relative_to('/build')),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files if p.is_file()],'pythonBuildTools':{n:m.version(n) for n in ['pip','setuptools','wheel']},'debianBuildPackages':subprocess.check_output(['dpkg-query','-W','-f=\u0024{binary:Package}\\t\u0024{Version}\\n'],text=True).splitlines()}; Path('/build/driver-build.json').write_text(json.dumps(report,indent=2)+'\\n')"

FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ARG LIBPQ_VERSION=15.19-0+deb12u1
ARG TZDATA_VERSION=2026f-0+deb12u1
ARG CREMA_VERSION=development
ARG CREMA_REVISION=unknown
LABEL org.opencontainers.image.title="Crema" \
      org.opencontainers.image.version=$CREMA_VERSION \
      org.opencontainers.image.revision=$CREMA_REVISION \
      org.opencontainers.image.description="Coffee production planning; dependencies retain their own licenses"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PSYCOPG_IMPL=c
WORKDIR /srv
COPY requirements.txt .
COPY --from=driver-build /build/wheels/ /tmp/driver-wheels/
COPY --from=driver-build /build/sources/ /usr/share/crema/sources/
COPY --from=driver-build /build/driver-build.json /usr/share/crema/driver-build.json
RUN chmod 0444 /usr/share/crema/sources/psycopg_c-3.3.6.tar.gz \
    && apt-get update && apt-get install --yes --no-install-recommends libpq5=${LIBPQ_VERSION} tzdata=${TZDATA_VERSION} \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.2 \
    && python -m pip install --no-cache-dir --find-links=/tmp/driver-wheels --only-binary=psycopg-c -r requirements.txt \
    && rm -rf /tmp/driver-wheels \
    && python -m pip uninstall --yes pip \
    && python -c "from pathlib import Path; import ensurepip; [p.unlink() for p in (Path(ensurepip.__file__).parent / '_bundled').glob('*.whl')]" \
    && useradd -u 10001 -r -s /usr/sbin/nologin portal
COPY . .
RUN python build_notices.py && PORTAL_BUILD=1 DJANGO_SECRET_KEY=build-only-placeholder-do-not-use-in-production python manage.py collectstatic --noinput && chmod +x /srv/entrypoint.sh && chmod -R a+rX /srv && mkdir -p /var/lib/roastery-secrets && chown 10001:10001 /var/lib/roastery-secrets && chmod 755 /var/lib/roastery-secrets
USER 10001:10001
EXPOSE 8000
CMD ["/srv/entrypoint.sh"]
