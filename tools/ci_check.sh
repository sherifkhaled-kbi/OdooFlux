#!/usr/bin/env bash
# The single definition of "a commit passes". CI (.github/workflows/ci.yml) and developers run the same script.
#   tools/ci_check.sh [tests|gates|package|all]     (default: all)
#   tests    full default test suite (stdlib only; opt-in suites stay skipped)
#   gates    Knowledge Base validation, generated documents in sync, requirements traceability
#   package  build the wheel and run the installed-wheel tests in a clean venv
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
PY="${PYTHON:-python3}"
step() { printf '\n==> %s\n' "$*"; }

tests() {
    step "test suite"
    "$PY" -m unittest discover -s tests -p 'test_*.py' -t .
}

gates() {
    step "knowledge validate"
    "$PY" -m odooflux knowledge validate
    step "compatibility matrix is up to date"
    "$PY" -m odooflux knowledge matrix --check
    step "support statement is up to date"
    "$PY" -m odooflux support-statement --check
    step "requirements traceability (RTM)"
    "$PY" tests/unit/release/rtm_tools.py
}

package() {
    step "wheel build and installed-wheel tests"
    ODOOFLUX_PACKAGING_INSTALL=1 "$PY" -m unittest discover -s tests/integration/packaging -p 'test_*.py' -t . -v
}

case "${1:-all}" in
    tests) tests ;;
    gates) gates ;;
    package) package ;;
    all) gates; tests; package ;;
    *) echo "usage: $0 [tests|gates|package|all]" >&2; exit 2 ;;
esac
step "OK: ${1:-all}"
