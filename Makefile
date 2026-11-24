SHELL := /bin/bash

# A pre-push hook runs with GIT_DIR naming this repository; nothing here runs
# git on the host, and this keeps it that way should something start to.
unexport GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR \
         GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_PREFIX

.PHONY: help ci-local ci-local-deep ci-remote test lint check image fmt install-hooks

DOCKER      := DOCKER_BUILDKIT=1 docker
PY_VERSION  := 3.12
CHECK       := meridian-sec-edgar-check
IMAGE       ?= sec-edgar:local
# The SDK pyproject.toml pins, and its base image. Where the sibling
# meridian-python checkout carries exactly that version -- one not yet
# published, being tried -- it is built from there (SDK_REPO): the tests' and
# the check's containers install it from source, and the plugin's image is
# built on a base made from it. Otherwise both come from PyPI and ghcr.io.
SDK_VERSION := $(shell sed -n 's/.*"open-meridian==\([0-9][0-9.]*\)".*/\1/p' pyproject.toml)
SDK_REPO    ?= $(if $(shell grep -s '^version = "$(SDK_VERSION)"$$' ../meridian-python/pyproject.toml),../meridian-python,)
SDK_CONTEXT := $(if $(SDK_REPO),--build-context sdk=$(SDK_REPO),)
# The released base is the Dockerfile's, by tag and digest.
BASE        ?= $(if $(SDK_REPO),plugin-python:$(SDK_VERSION)-local,$(shell sed -n 's/^ARG BASE=//p' Dockerfile))
PLUGIN_CHECK := meridian-sec-edgar-plugin-check
# The meridian check.yaml holds the plugin to, read from there so the two
# cannot drift.
MERIDIAN_VERSION := $(shell sed -n 's/^ *MERIDIAN_VERSION: *\([0-9][0-9.]*\).*/\1/p' .github/workflows/check.yaml)
# A meridian built locally (a directory holding its binary), for a release
# not yet published: `make check MERIDIAN_BIN=../cli-build`. Empty, the
# release check.yaml pins is installed.
MERIDIAN_BIN ?=
CLI_CONTEXT := $(if $(MERIDIAN_BIN),--build-context cli=$(MERIDIAN_BIN),)

help:
	@echo "  make ci-local       every gate: lint, tests, plugin check and the plugin's image (the pre-push gate)"
	@echo "  make ci-remote      what ci.yaml runs: lint and tests"
	@echo "  make test           the tests, in a container"
	@echo "  make lint           ruff and mypy, strict"
	@echo "  make check          what check.yaml runs: meridian plugin check --verified --run-tests, in a container"
	@echo "  make image          build the plugin's image, as upload would, and check it"
	@echo "  make fmt            apply the formatter"
	@echo "  make install-hooks  point git at hooks/ so push fires ci-local"

# Local green is the completion signal; CI is confirmation. Every CI job is a
# target reachable from here.
ci-local: ci-remote check image
	@echo
	@echo "ci-local: GREEN"

ci-local-deep: ci-local

ci-remote: lint test
	@echo
	@echo "ci-remote: GREEN"

lint:
	@$(DOCKER) build $(SDK_CONTEXT) -f Dockerfile.check --target lint . >/dev/null 2>&1 \
		|| { echo "lint FAILED; see it with:" >&2; \
		     echo "  DOCKER_BUILDKIT=1 docker build $(SDK_CONTEXT) -f Dockerfile.check --target lint --progress=plain ." >&2; exit 1; }
	@echo "lint OK: ruff and mypy (strict) clean"

test:
	@$(DOCKER) build $(SDK_CONTEXT) -f Dockerfile.check --target test -t $(CHECK) . >/dev/null 2>&1 \
		|| { echo "test FAILED to build; see it with:" >&2; \
		     echo "  DOCKER_BUILDKIT=1 docker build $(SDK_CONTEXT) -f Dockerfile.check --target test --progress=plain ." >&2; exit 1; }
	@docker run --rm $(CHECK) python -m pytest -q -rs >.test.log 2>&1 \
		|| { echo "test FAILED. The last 40 lines, and the whole of it in .test.log:" >&2; \
		     tail -40 .test.log >&2; exit 1; }
	@echo "test OK: $$(tail -1 .test.log)"

# check.yaml's job, in a container: the meridian it pins, installed as it is
# there, holds the plugin to the framework's rules and runs its tests. The
# repository is mounted read-only, and the check writes nothing to it.
check:
	@[ -n "$(MERIDIAN_VERSION)" ] \
		|| { echo "check FAILED: .github/workflows/check.yaml pins no MERIDIAN_VERSION" >&2; exit 1; }
	@$(DOCKER) build $(SDK_CONTEXT) -f Dockerfile.check --target check $(CLI_CONTEXT) --build-arg MERIDIAN_VERSION=$(MERIDIAN_VERSION) \
		-t $(PLUGIN_CHECK) . >/dev/null 2>&1 \
		|| { echo "check FAILED to build; see it with:" >&2; \
		     echo "  DOCKER_BUILDKIT=1 docker build $(SDK_CONTEXT) -f Dockerfile.check --target check $(CLI_CONTEXT) --build-arg MERIDIAN_VERSION=$(MERIDIAN_VERSION) --progress=plain ." >&2; exit 1; }
	@out="$$(docker run --rm -v "$(CURDIR)":/w:ro $(PLUGIN_CHECK) meridian plugin check --verified --run-tests 2>&1)" \
		|| { echo "check FAILED:" >&2; echo "$$out" >&2; exit 1; }
	@echo "check OK: meridian $(MERIDIAN_VERSION) plugin check --verified --run-tests, every rule holds"

# The image `meridian plugin upload` builds from this Dockerfile, checked for
# what a plugin's image must be: it starts as 65532, imports itself, its pages
# and its recorded answers, and carries nothing of this repository but the
# package.
image:
	@if [ -n "$(SDK_REPO)" ]; then \
		$(MAKE) --no-print-directory -C "$(SDK_REPO)" base-image BASE_IMAGE=$(BASE) >/dev/null \
			|| { echo "image FAILED: the base for open-meridian $(SDK_VERSION) was not built from $(SDK_REPO)" >&2; exit 1; }; \
	fi
	@$(DOCKER) build --build-arg BASE=$(BASE) -t $(IMAGE) . >/dev/null 2>&1 \
		|| { echo "image FAILED; see it with:" >&2; \
		     echo "  DOCKER_BUILDKIT=1 docker build --build-arg BASE=$(BASE) --progress=plain ." >&2; exit 1; }
	@[ "$$(docker inspect -f '{{.Config.User}}' $(IMAGE))" = "65532" ] \
		|| { echo "image FAILED: it does not run as 65532" >&2; exit 1; }
	@docker run --rm --entrypoint python $(IMAGE) -c \
		"import meridian, sec_edgar.__main__, sec_edgar.page; from sec_edgar.edgar import SyntheticApi; assert len(SyntheticApi().answers) == 5" \
		|| { echo "image FAILED: it does not import the SDK, itself and its recorded answers" >&2; exit 1; }
	@[ "$$(docker run --rm --entrypoint sh $(IMAGE) -c 'ls -A /plugin')" = "docs" ] \
		|| { echo "image FAILED: /plugin holds files beyond docs/; only the installed package and its documentation belong" >&2; exit 1; }
	@echo "image OK: $(IMAGE) on $(BASE), $$(docker image inspect -f '{{.Size}}' $(IMAGE) | awk '{printf "%.0f MB", $$1/1e6}')"

# Applied in a container and written back, because the host has no toolchain.
fmt:
	@docker run --rm -v "$(CURDIR)":/w -w /w python:$(PY_VERSION)-slim \
		sh -c 'pip install -q ruff >/dev/null 2>&1; python -m ruff check --fix src tests >/dev/null; python -m ruff format src tests'
	@echo "fmt: applied"

install-hooks:
	@git config core.hooksPath hooks
	@echo "hooks installed: git push now runs 'make ci-local' first"
