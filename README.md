# PolyAI

## Setup

Create and activate a virtual environment from the repo root directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your terminal prompt should now show `(.venv)`. Keep this environment active whenever you run any service.

See each service's README for how to configure and run it.

## Docker Compose Files

Use the compose files by environment:

- `compose.yaml`: normal EC2/prod/dev deployment. It runs prebuilt images from
  the image tags in `.env`.
- `compose.ec2.yaml`: EC2 source-build override. Use only when you intentionally
  want to build images from the code checked out on the EC2 instance.
- `compose.local.yaml`: local laptop development override only. Do not use it on
  EC2 because it mounts `~/.aws` and sets `AWS_PROFILE`.

Normal EC2 deployment after GitHub Actions builds images:

```bash
docker compose pull
docker compose up -d --remove-orphans
```

Emergency EC2 source build from checked-out code:

```bash
docker compose -f compose.yaml -f compose.ec2.yaml build --no-cache
docker compose -f compose.yaml -f compose.ec2.yaml up -d --remove-orphans
```

Local laptop build:

```bash
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```
