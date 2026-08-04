# Thin wrapper. The task list lives in tools/tasks.py so that Windows - where
# `make` does not exist and practically every user of this package is - gets
# identical behaviour through make.cmd. See docs/building.md.

PYTHON ?= python3
TASKS  := $(PYTHON) -m tools.tasks

.PHONY: help build dry-run validate test check bindings package-def preview sweep clean

help:
	@$(TASKS) help

build:
	@$(TASKS) build

dry-run:
	@$(TASKS) dry-run

validate:
	@$(TASKS) validate

test:
	@$(TASKS) test

check:
	@$(TASKS) check

bindings:
	@$(TASKS) bindings

package-def:
	@$(TASKS) package-def

preview:
	@$(TASKS) preview

sweep:
	@$(TASKS) sweep

clean:
	@$(TASKS) clean
