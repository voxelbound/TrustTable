# Release images

How TrustTable's container images are named, built and published, and what a
person with only GitHub and the GitHub Container Registry (GHCR) runs.

> **Status: defined, not yet published or verified.** The pull-only Compose
> file and the publish workflow exist and are tested, but **no image has been
> published and the workflow has never run against a real registry.** Until a
> release exists, `docker compose up --build` from a checkout is the only
> supported install (see [`installation-linux.md`](installation-linux.md)).

## What is published

| Image | Built from |
|---|---|
| `ghcr.io/voxelbound/trusttable-backend` | `backend/Dockerfile` |
| `ghcr.io/voxelbound/trusttable-frontend` | `frontend/Dockerfile` |

- **Tag scheme:** the version without the leading `v` — git tag `v0.2.0`
  publishes `…:0.2.0`. There is **no `latest` tag**: a pull-only install is
  always a specific, reproducible release.
- **Platform:** `linux/amd64`, the formally supported Linux target.
- **No attestations yet:** provenance and SBOM attestations are disabled.
  SBOM generation, container scanning and signing belong to the later security
  and release-artifact work, not to this path.
- The backend package version (`backend/pyproject.toml`) is what
  `GET /api/v1/version` reports. A release tag must equal it exactly, so the
  version a running backend reports is the tag it was installed from.

## What a person runs (once a release is published)

```sh
git clone --branch v<version> --depth 1 https://github.com/voxelbound/trusttable.git
cd trusttable
TRUSTTABLE_VERSION=<version> docker compose -f docker-compose.release.yml up -d
```

`docker-compose.release.yml` is the pull-only twin of `docker-compose.yml`:
the same two services, ports, restart policy, health checks and host-gateway
mapping, but it names the published images instead of building them, so the host
needs only GitHub and GHCR — not the container base-image registry, PyPI or npm.
`TRUSTTABLE_VERSION` is required and has no default; Compose refuses to start
without it. A test keeps the two files identical apart from where the images
come from.

## What the workflow does

`.github/workflows/release-images.yml`:

1. **Check the version.** For a tag it must look like `vMAJOR.MINOR.PATCH` and
   equal the backend package version, otherwise nothing is built for
   publishing. The ref name is passed to the script only through an environment
   variable, never interpolated into shell.
2. **Build both images** (`linux/amd64`). The build runs for a manual run too,
   but **only the first attempt of a pushed version tag publishes**: the
   registry login and the push are both conditional on the event being a `push`
   of a tag with `run_attempt == 1`, and only this job holds `packages: write`
   (the workflow's default permission is `contents: read`).
3. **Verify the published images without credentials.** After a tag publish, a
   job with **no registry login** pulls both images at that tag, starts the
   pull-only Compose file, and checks backend health, that the reported version
   equals the tag, and that the frontend answers. A package that is still
   private, or was never published, fails here instead of being assumed
   reachable.

Pull requests, branch pushes and manual runs never publish — **including a
manual run started from a tag**, which is not a tag push. **A re-run never
publishes either**: only the first attempt does, so a published version is never
overwritten. The verification job is the exception that may be re-run, because
it only pulls. If a publish fails part-way (one image pushed, the other not), the
version is superseded by a new one rather than completed by a re-run.

## What stays a human action

Publishing is a protected release action. These are deliberately **not**
performed by any workflow or automation, and each needs explicit authority:

- **Pushing the version tag.** The tag is the act that authorizes a publish.
  Pushing it (or creating a GitHub release from it) is what starts the workflow.
- **Package visibility.** A package first published by a workflow may be private
  by default. If the anonymous-pull verification fails for that reason, making
  the package public is a repository-owner action taken in GitHub's package
  settings, after which the verification can be re-run.
- **Removing or replacing a published tag.** Published tags are neither removed
  nor overwritten as routine recovery (a re-run does not push, see above); a bad
  or incomplete release is superseded by a new version.

## First-publish checklist

1. Bump `backend/pyproject.toml` (and `backend/uv.lock`) to the release version
   and merge it.
2. Confirm CI is green on `main`.
3. Push the tag `v<version>` (protected action).
4. Watch the workflow: check the version → build and publish → verify the
   anonymous pull.
5. If the anonymous pull fails because the packages are private, change their
   visibility (protected action) and re-run only the verification job (it
   re-runs safely; nothing is pushed).
6. On a fresh Linux host that can reach only GitHub and GHCR, follow
   [`installation-linux.md`](installation-linux.md) with the published version
   and record the result; update the guide to what actually passed.

## See also

- [`installation-linux.md`](installation-linux.md) — install and run on Linux.
- [`docker-compose.release.yml`](../docker-compose.release.yml) — the pull-only file.
- [`decision-log.md`](decision-log.md), `D-041` — why the path is shaped this way.
