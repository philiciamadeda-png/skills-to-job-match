I need to deploy a Django 5 project to [your chosen host]. It uses PostgreSQL, Redis, a Celery worker and Celery beat, and currently runs locally with docker-compose.

Walk me through: the production settings that must differ from local, serving static files, the Dockerfile or build configuration, running migrations as part of deployment, and deploying the worker and beat as separate processes rather than only the web app.

Then give me a checklist of the specific errors a Django project usually hits on its first production deploy, what each one looks like, and how to fix it — I would rather recognise them than debug them from scratch.

---

Host chosen: **Render** (see `docs/deployment.md` §1 for why). Language models are not part of the deployment (§8). The answer is `docs/deployment.md`, with `Dockerfile`, `render.yaml` and `config/settings/production.py`.
