# One-command entry points. `make eval` is the judging protocol.
TASK  ?= tasks/depot-basic-s7
MODEL ?=
RUNS  ?= 3

.PHONY: setup test build check audit anchors eval play

setup:            ## create the virtualenv and install Harbor
	uv sync
	uv tool install harbor

test:             ## unit tests, including the MCP round trip
	uv run pytest

build:            ## recalibrate and regenerate tasks/ (run after any change to an environment or scenario)
	uv run envkit build

check:            ## fail if calibration.json or tasks/ are stale
	uv run envkit check

audit:            ## reward-integrity checks, in-process
	uv run envkit audit

anchors:          ## score table for every scripted policy, in-process
	uv run envkit anchors

eval:             ## reference + do-nothing + stop-early (+ $(RUNS) agent runs if MODEL is set), through Harbor
	uv run envkit eval $(TASK) $(if $(MODEL),--model $(MODEL)) --runs $(RUNS)

play:             ## play by hand: make play SCENARIO=depot-basic
	uv run envkit play $(or $(SCENARIO),depot-basic)
