# Joinr

Identity lifecycle platform (Joiner · Mover · Leaver) for personal use.

Built with Django, PostgreSQL, Redis and Docker Compose.

## Run

```bash
docker compose up --build -d
```

Open <http://localhost:8000>. The first start runs migrations and collects static files, which takes several minutes.

## Develop

- `make dev` starts the development stack.
- Settings live in `joinr/settings/`; copy `.env.dist` to `.env` and adjust it.
- Local-only secrets belong in `.env` (git-ignored). The compose file's values are weak development defaults.
