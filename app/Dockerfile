FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS driver-build
ARG LIBPQ_VERSION=15.19-0+deb12u1
ARG JPEG_VERSION=1:2.1.5-2
ARG WEBP_VERSION=1.2.4-0.2+deb12u1
ARG FFI_VERSION=3.4.4-1
ARG ZLIB_VERSION=1:1.2.13.dfsg-1
WORKDIR /build
RUN apt-get update && apt-get install --yes --no-install-recommends gcc g++ libc6-dev pkg-config libpq-dev=${LIBPQ_VERSION} libjpeg62-turbo-dev=${JPEG_VERSION} libwebp-dev=${WEBP_VERSION} libffi-dev=${FFI_VERSION} zlib1g-dev=${ZLIB_VERSION} \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir pip==26.2.2 setuptools==83.0.0 wheel==0.48.0 pybind11==3.0.1 pycparser==3.12 packaging==26.3
# Retain the exact C extension source, including its license and build backend.
ADD --checksum=sha256:29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8 https://files.pythonhosted.org/packages/58/53/bf15aa48cd6f0ad0039b9f48681d2e76e8564d413af47b13fab50dd03555/psycopg_c-3.3.6.tar.gz /build/sources/psycopg_c-3.3.6.tar.gz
ADD --checksum=sha256:cdcd1ba258178f7356d74170c9a81ba4eab6a5d55748bc402a5a2a6fe6be3510 https://files.pythonhosted.org/packages/ce/a4/9cc30690a394a8305e8be4c9036aa16d0dfddadd09079860b582f562496d/pillow-13.0.0.tar.gz /build/sources/pillow-13.0.0.tar.gz
ADD --checksum=sha256:dd31f52ea1086513bb9df30f8fcee9b8918323ae067a3d5b78bc826a000712be https://files.pythonhosted.org/packages/9e/ef/008a1939e372c06329a3fce4279c02f328488f3526744906eeec3da7ad5f/cffi-2.1.1.tar.gz /build/sources/cffi-2.1.1.tar.gz
RUN python -m pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /build/wheels /build/sources/psycopg_c-3.3.6.tar.gz \
    && python -m pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /build/wheels /build/sources/cffi-2.1.1.tar.gz \
    && python -m pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /build/wheels /build/sources/pillow-13.0.0.tar.gz -C parallel=2 -C zlib=enable -C jpeg=enable -C webp=enable -C tiff=disable -C freetype=disable -C raqm=disable -C lcms=disable -C jpeg2000=disable -C imagequant=disable -C xcb=disable -C avif=disable \
    && python -c "import json,hashlib,importlib.metadata as m,subprocess; from pathlib import Path; files=list(Path('/build').glob('*/*')); report={'format':'crema-native-build-v2','implementation':'psycopg-c','nativeBuilds':['psycopg-c','Pillow','cffi'],'pillowCodecs':['JPEG','PNG','WEBP'],'files':[{'path':str(p.relative_to('/build')),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files if p.is_file()],'pythonBuildTools':{n:m.version(n) for n in ['pip','setuptools','wheel','pybind11','pycparser']},'debianBuildPackages':subprocess.check_output(['dpkg-query','-W','-f=\u0024{binary:Package}\\t\u0024{Version}\\n'],text=True).splitlines()}; Path('/build/driver-build.json').write_text(json.dumps(report,indent=2)+'\\n')"

FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ARG LIBPQ_VERSION=15.19-0+deb12u1
ARG TZDATA_VERSION=2026f-0+deb12u1
ARG JPEG_VERSION=1:2.1.5-2
ARG WEBP_VERSION=1.2.4-0.2+deb12u1
ARG FFI_VERSION=3.4.4-1
ARG ZLIB_VERSION=1:1.2.13.dfsg-1
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
RUN chmod 0444 /usr/share/crema/sources/*.tar.gz \
    && apt-get update && apt-get install --yes --no-install-recommends libpq5=${LIBPQ_VERSION} tzdata=${TZDATA_VERSION} libjpeg62-turbo=${JPEG_VERSION} libwebp7=${WEBP_VERSION} libwebpdemux2=${WEBP_VERSION} libwebpmux3=${WEBP_VERSION} libffi8=${FFI_VERSION} zlib1g=${ZLIB_VERSION} \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.2 \
    && python -m pip install --no-cache-dir --no-deps /tmp/driver-wheels/*.whl \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check \
    && rm -rf /tmp/driver-wheels \
    && python -m pip uninstall --yes pip \
    && python -c "from pathlib import Path; import ensurepip; [p.unlink() for p in (Path(ensurepip.__file__).parent / '_bundled').glob('*.whl')]" \
    && useradd -u 10001 -r -s /usr/sbin/nologin portal
COPY . .
RUN python build_notices.py && PORTAL_BUILD=1 DJANGO_SECRET_KEY=build-only-placeholder-do-not-use-in-production python manage.py collectstatic --noinput && chmod +x /srv/entrypoint.sh && chmod -R a+rX /srv && mkdir -p /var/lib/roastery-secrets && chown 10001:10001 /var/lib/roastery-secrets && chmod 755 /var/lib/roastery-secrets
USER 10001:10001
EXPOSE 8000
CMD ["/srv/entrypoint.sh"]
