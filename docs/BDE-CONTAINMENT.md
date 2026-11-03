# BDE execution boundary

Local execution is advisory and requires explicit consent (`--allow-local` or
`SHIPGUARD_ALLOW_LOCAL=1`). Use it only for code trusted to run as the current OS
user. `discover`, `check` and `reproduce` support a fail-closed Docker option:

```sh
docker build -t shipguard-bde -f docker/bde/Dockerfile docker/bde
export SHIPGUARD_BDE_IMAGE=$(docker image inspect shipguard-bde --format '{{.Id}}')
shipguard discover --repo /path/to/committed/repo --module src/index.ts \
  --runner docker --image "$SHIPGUARD_BDE_IMAGE" --out /path/to/evidence
```

The pinned image uses Node 20.20.2 and tsx 4.20.6. The runner refuses mutable image
tags, never pulls automatically and never falls back to local execution. Network
is disabled; source, engine and lawpack mounts are read-only; no host credentials
or Docker socket are mounted. UID/GID 65534, dropped capabilities,
no-new-privileges, 64 PIDs, 256 MiB RAM/no swap, one CPU, 256 open files and a
32 MiB non-executable tmpfs limit target access. External supervision caps total
output at 4 MB and wall time at 1200 seconds (12 seconds per law); cleanup removes
the entire container including detached children.

Mandatory `bde_containment` tests execute actual negative probes for network,
credentials, writes, UID, process limits, memory exhaustion, output flooding,
wall timeout/detached children and a mutable image. They run in their own CI job;
missing Docker/image prerequisites fail rather than skip.

The Docker daemon, image and host kernel are trusted. Target code shares a worker
with predicate instrumentation; hostile code may tamper with observations. This
is containment, not an independent semantic oracle, proof against container
escape, or an unbypassable execution gate. Independent verification must use
separately controlled requirements and tests. Checksums identify artifacts but do
not authenticate their author. Only clean committed snapshots with tracked
runtime dependencies are suitable for reproducible evaluation; external
symlinked dependencies can fail in Docker. Dependency installation is a separate
provisioning operation and must not inherit host credentials.

Mutation probes remain a developer diagnostic using explicitly trusted local
code; they do not offer Docker containment and must not be used on untrusted
repositories. No untrusted mutation service is supported. Unsupported async or
unextractable source shapes remain visible in coverage rather than becoming passes.
