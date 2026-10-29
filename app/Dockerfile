FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -r -s /usr/sbin/nologin portal
COPY . .
RUN PORTAL_BUILD=1 DJANGO_SECRET_KEY=build-only-placeholder-do-not-use-in-production python manage.py collectstatic --noinput && chmod +x /srv/entrypoint.sh && chmod -R a+rX /srv && mkdir -p /var/lib/roastery-secrets && chown 10001:10001 /var/lib/roastery-secrets && chmod 755 /var/lib/roastery-secrets
USER 10001:10001
EXPOSE 8000
CMD ["/srv/entrypoint.sh"]
