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
  the image tags in `.env`. EC2 should use this file only.
- `compose.local.yaml`: local laptop development override only. Do not use it on
  EC2 because it mounts `~/.aws` and sets `AWS_PROFILE`.

Normal EC2 deployment after GitHub Actions builds images:

```bash
docker compose pull
docker compose up -d --remove-orphans
```

Local laptop build:

```bash
docker compose -f compose.yaml -f compose.local.yaml build --no-cache
docker compose -f compose.yaml -f compose.local.yaml up -d
```

## Optional AI Agent Skills

The application and Terraform configuration do not require agent skills to run.
Developers using Codex or another compatible coding agent can optionally install
HashiCorp's agent skills for Terraform assistance:

```bash
npx skills add hashicorp/agent-skills
```

The most relevant skills for this repository are:

- `terraform-style-guide`
- `refactor-module`
- `terraform-test` when adding Terraform tests

Installed skill directories are local development tools and should not be
committed with the application or infrastructure code.
