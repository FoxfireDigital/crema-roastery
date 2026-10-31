FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ARG CREMA_VERSION=development
ARG CREMA_REVISION=unknown
LABEL org.opencontainers.image.title="Crema" \
      org.opencontainers.image.version=$CREMA_VERSION \
      org.opencontainers.image.revision=$CREMA_REVISION \
      org.opencontainers.image.description="Coffee production planning; dependencies retain their own licenses"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.2 \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall --yes pip \
    && python -c "from pathlib import Path; import ensurepip; [p.unlink() for p in (Path(ensurepip.__file__).parent / '_bundled').glob('*.whl')]" \
    && useradd -u 10001 -r -s /usr/sbin/nologin portal
COPY . .
RUN python build_notices.py && PORTAL_BUILD=1 DJANGO_SECRET_KEY=build-only-placeholder-do-not-use-in-production python manage.py collectstatic --noinput && chmod +x /srv/entrypoint.sh && chmod -R a+rX /srv && mkdir -p /var/lib/roastery-secrets && chown 10001:10001 /var/lib/roastery-secrets && chmod 755 /var/lib/roastery-secrets
USER 10001:10001
EXPOSE 8000
CMD ["/srv/entrypoint.sh"]
