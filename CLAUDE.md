# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

Buildfarm is a remote caching and execution system implementing the [Remote
APIs](https://github.com/bazelbuild/remote-apis) specification. It is
compatible with Bazel, buck2, pants, and other build systems. The server
coordinates work via a Redis backplane; workers poll the backplane, fetch
inputs from CAS, execute actions (optionally in Docker/cgroups sandboxes), and
upload outputs.

## Build System

Bazel 9.0.1 with bzlmod enabled (version pinned in `.bazelversion`). Java 21
language level and runtime.

```bash
# Build everything
bazel build //src/main/java/build/buildfarm/...

# Run all tests (redis and integration tests excluded by default; see .bazelrc)
bazel test //src/test/java/build/buildfarm/...

# Run tests for a specific package
bazel test //src/test/java/build/buildfarm/common/config:tests

# Run a single test class (--test_filter takes the fully-qualified class name)
bazel test //src/test/java/build/buildfarm/cas:tests --test_filter=build.buildfarm.cas.MemoryCASTest

# Include redis/integration tests (overrides .bazelrc tag filters)
bazel test //src/test/java/build/buildfarm/... --test_tag_filters=
```

## Running Locally

```bash
# Valkey (Redis-compatible drop-in for Redis) instance
docker run \
    --detach \
    --name=buildfarm-redis \
    --publish=6379:6379 \
    --rm \
        valkey

# Server (default gRPC port: 8980)
bazel run //src/main/java/build/buildfarm:buildfarm-server \
    -- \
    --jvm_flag=-Djava.util.logging.config.file="$PWD/examples/logging.properties" \
        "$PWD/examples/config.minimal.yml"

# Worker
bazel run //src/main/java/build/buildfarm:buildfarm-shard-worker \
    -- \
    --jvm_flag=-Djava.util.logging.config.file="$PWD/examples/logging.properties" \
        "$PWD/examples/config.minimal.yml"

# Remote debugger
bazel run //src/main/java/build/buildfarm:buildfarm-server \
    -- \
    --debug=5005 \
        "$PWD/examples/config.minimal.yml"
```

## Code Formatting and Linting

Pre-commit hooks enforce formatting (`pre-commit install` to set up).

```bash
# Format all code (Java via google-java-format, BUILD files via buildifier, license headers via hawkeye)
./.bazelci/format.sh

# Check formatting without modifying (used in CI)
./.bazelci/format.sh --check

# Checkstyle static analysis
./.bazelci/run_checkstyle.sh

# Buildifier only
bazel run //:buildifier
```

Checkstyle (`.bazelci/checkstyle_checks.xml`) checks for following `import`s:
- `*`
- unused
- redundant

## Architecture

Client sends an action via gRPC to **server**, which queues it in the
Redis-based **backplane**. A **worker** polls the backplane, fetches action
inputs from **CAS**, executes in a Docker/cgroups sandbox, uploads outputs back
to CAS, and the server returns results to the client. The **action cache**
short-circuits this flow when a matching result already exists.

```
src/main/java/build/buildfarm/
  server/       # gRPC server: receives client requests, queues actions via backplane
  worker/       # Execution engine: polls backplane, runs actions in Docker/cgroups/sandbox
  backplane/    # Redis-based coordination: operation queues, worker registration
  cas/          # Content Addressable Storage: stores/retrieves blobs by digest
  actioncache/  # Action cache: maps actions to cached results
  instance/     # Instance abstractions (shard for distributed, stub for remote proxy)
  common/       # Shared utilities: config parsing, gRPC helpers, I/O, digest functions
  metrics/      # Prometheus metrics exposition
  proxy/        # Proxy layer implementations
  tools/        # CLI utilities (e.g., bf-cat)

src/main/protobuf/  # Protobuf service/message definitions (build.buildfarm.v1test)
persistentworkers/  # Persistent worker implementations
container/          # OCI/Docker image definitions (server + worker images)
examples/           # YAML config files and logging.properties
kubernetes/         # Helm charts for deployment
```

## Key Conventions

Tests use JUnit 4 with Mockito; assertions use Google Truth.

Nullability annotations: `org.jspecify.annotations.Nullable` (not jsr305).

Configuration is YAML-based (see `examples/config.minimal.yml` for schema).

License: Apache 2.0 -- all source files require license headers (enforced by
hawkeye).

Protobuf definitions generate Java code via Bazel rules; edit `.proto` files,
not generated code.

Lombok is used in source files. Classes annotated with `@Getter`,
`@Setter`, `@Builder`, `@Data`, _etc_ have methods generated at compile time
that do not appear in source.

Error Prone (`error_prone_core`) runs at compile time and may reject code that
javac alone would accept (e.g., unused variables, unsafe casts).

Docker images are built via Bazel:
```bash
bazel build //container:buildfarm-server //container:buildfarm-worker
```
