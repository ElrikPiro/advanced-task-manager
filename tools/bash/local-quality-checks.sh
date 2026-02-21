#!/usr/bin/env bash
# Local Quality Checks Script
# Replicates the CI/CD pipeline quality checks locally for Debian/Linux development
# Based on .github/workflows/ci-cd.yaml

set -euo pipefail

# ========================================
# ARGUMENT PARSING
# ========================================
SKIP_LINT=false
SKIP_TESTS=false
SKIP_COVERAGE=false
SKIP_TYPE_CHECK=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-lint)      SKIP_LINT=true; shift ;;
        --skip-tests)     SKIP_TESTS=true; shift ;;
        --skip-coverage)  SKIP_COVERAGE=true; shift ;;
        --skip-typecheck) SKIP_TYPE_CHECK=true; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-lint       Skip flake8 linting checks"
            echo "  --skip-tests      Skip unit tests"
            echo "  --skip-coverage   Skip code coverage analysis"
            echo "  --skip-typecheck  Skip MyPy type checking"
            echo "  --help, -h        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ========================================
# UTILITY FUNCTIONS
# ========================================
ALL_PASSED=true
declare -a CHECK_RESULTS=()

write_section() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "============================================================"
}

run_check() {
    local check_name="$1"
    shift
    echo "Running: $*"
    if "$@"; then
        echo "[PASS] $check_name - PASSED"
        return 0
    else
        echo "[FAIL] $check_name - FAILED"
        ALL_PASSED=false
        return 1
    fi
}

# ========================================
# RESOLVE PROJECT ROOT
# ========================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON="${PYTHON:-python3}"

echo "*** Starting Local Quality Checks for Advanced Task Manager ***"
echo "Project Root: $PROJECT_ROOT"
echo "Python Version: $($PYTHON --version 2>&1)"

# ========================================
# DEPENDENCY INSTALLATION
# ========================================
write_section "Installing Dependencies"

echo "Upgrading pip..."
run_check "Pip Upgrade" $PYTHON -m pip install --upgrade pip || true

if [[ "$SKIP_LINT" == false ]] || [[ "$SKIP_TYPE_CHECK" == false ]]; then
    echo "Installing linting dependencies..."
    run_check "Lint Dependencies" pip install flake8 mypy || true
fi

if [[ "$SKIP_TESTS" == false ]] || [[ "$SKIP_COVERAGE" == false ]]; then
    echo "Installing project dependencies..."
    run_check "Project Dependencies" pip install -r requirements.txt || true
fi

if [[ "$SKIP_COVERAGE" == false ]]; then
    echo "Installing coverage..."
    run_check "Coverage Dependency" pip install coverage || true
fi

# ========================================
# LINTING
# ========================================
if [[ "$SKIP_LINT" == false ]]; then
    write_section "Code Linting with Flake8"

    if run_check "Flake8 Linting" flake8 --ignore=E501,E266,W293 backend/src/; then
        CHECK_RESULTS+=("Flake8 Linting: PASSED")
    else
        CHECK_RESULTS+=("Flake8 Linting: FAILED")
    fi
else
    echo "[SKIP] Skipping linting checks"
fi

# ========================================
# TYPE CHECKING
# ========================================
if [[ "$SKIP_TYPE_CHECK" == false ]]; then
    write_section "Type Checking with MyPy"

    if run_check "MyPy Type Checking" mypy backend/src/ --strict --ignore-missing-imports --show-error-codes --warn-unused-ignores; then
        CHECK_RESULTS+=("MyPy Type Checking: PASSED")
    else
        CHECK_RESULTS+=("MyPy Type Checking: FAILED")
    fi
else
    echo "[SKIP] Skipping type checking"
fi

# ========================================
# UNIT TESTS
# ========================================
if [[ "$SKIP_TESTS" == false ]]; then
    write_section "Running Unit Tests"

    if (cd backend && run_check "Unit Tests" $PYTHON -m unittest discover -s tests -p '*_test.py'); then
        CHECK_RESULTS+=("Unit Tests: PASSED")
    else
        CHECK_RESULTS+=("Unit Tests: FAILED")
    fi
else
    echo "[SKIP] Skipping unit tests"
fi

# ========================================
# CODE COVERAGE
# ========================================
if [[ "$SKIP_COVERAGE" == false ]]; then
    write_section "Code Coverage Analysis"

    echo "Running tests with coverage..."
    coverage_passed=true
    if (cd backend && run_check "Coverage Run" coverage run -m unittest discover -s tests -p '*_test.py'); then
        echo "Generating coverage report..."
        (cd backend && run_check "Coverage Report" coverage report -m) || coverage_passed=false

        echo "Checking coverage threshold (80%)..."
        (cd backend && run_check "Coverage Threshold" coverage report --fail-under=80) || coverage_passed=false
    else
        coverage_passed=false
    fi

    if [[ "$coverage_passed" == true ]]; then
        CHECK_RESULTS+=("Code Coverage: PASSED")
    else
        CHECK_RESULTS+=("Code Coverage: FAILED")
        ALL_PASSED=false
    fi
else
    echo "[SKIP] Skipping coverage analysis"
fi

# ========================================
# SUMMARY REPORT
# ========================================
write_section "Quality Checks Summary"

for result in "${CHECK_RESULTS[@]}"; do
    echo "  $result"
done

echo ""
if [[ "$ALL_PASSED" == true ]]; then
    echo "*** All quality checks PASSED! Ready for commit/push. ***"
    exit 0
else
    echo "*** Some quality checks FAILED! Please fix issues before committing. ***"
    exit 1
fi
