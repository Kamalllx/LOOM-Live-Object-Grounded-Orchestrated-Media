# LOOM Local Infrastructure

MongoDB and Redis are optional local services for Person 4. The web player uses
the file memory driver by default, so Docker is only needed when demonstrating
durable Mongo persistence or Redis caching.

## Start

```bash
cd services/delivery/infra
docker compose up -d
docker compose ps
```

Then create `services/delivery/web/.env.local` from `.env.example` and set:

```env
MEMORY_DRIVER=mongo
MONGODB_URI=mongodb://loom:loom_dev_password@localhost:27018/loom?authSource=admin
MONGODB_DB=loom
```

Restart the web server after changing environment variables.

## Services

| Service | Host port | Purpose |
| --- | ---: | --- |
| MongoDB | 27018 | Learner profiles and session logs |
| Redis | 6380 | Optional learner-profile cache |
| Mongo Express | 8081 | Optional inspection UI |

Start Mongo Express for a demo with:

```bash
docker compose --profile tools up -d
```

Open <http://localhost:8081>. The database is `loom`, with collections:

- `learner_memory`, keyed by `learner_id`
- `session_logs`, keyed by `session_id`

## Stop and reset

```bash
docker compose down       # stop containers, preserve data
docker compose down -v     # stop containers and delete volumes
```

The initialization script runs only when the Mongo volume is first created.



