# PowerShell Quality Checks Script

## Overview

The `local-quality-checks.ps1` script replicates the same quality checks that run in the CI/CD pipeline (`.github/workflows/ci-cd.yaml`) locally on Windows systems.

## Features

This script performs the following quality checks:

1. **Dependency Installation**
   - Upgrades pip
   - Installs linting dependencies (flake8, mypy)
   - Installs project dependencies from `requirements.txt`
   - Installs coverage tools

2. **Code Linting (Flake8)**
   - Runs flake8 with the same ignore rules as CI/CD
   - Ignores: E501 (line too long), E266 (too many leading # for block comment), W293 (blank line contains whitespace)

3. **Type Checking (MyPy)**
   - Performs strict type checking on `backend/src/`
   - Uses the same flags as CI/CD: `--strict --ignore-missing-imports --show-error-codes --warn-unused-ignores`

4. **Unit Tests**
   - Discovers and runs all `*_test.py` files in the `backend/tests/` directory (247 tests)
   - Uses Python's built-in unittest framework
   - Matches the exact CI/CD command: `python -m unittest discover -s tests -p "*_test.py"`

5. **Code Coverage**
   - Runs tests with coverage analysis
   - Generates coverage reports
   - Enforces 80% minimum coverage threshold (same as CI/CD)

## Usage

### Basic Usage
```powershell
# Run all quality checks
.\tools\powershell\local-quality-checks.ps1

# Run with execution policy bypass (if needed)
powershell -ExecutionPolicy Bypass -File .\tools\powershell\local-quality-checks.ps1
```

### Skip Specific Checks
```powershell
# Skip linting
.\tools\powershell\local-quality-checks.ps1 -SkipLint

# Skip type checking
.\tools\powershell\local-quality-checks.ps1 -SkipTypeCheck

# Skip unit tests
.\tools\powershell\local-quality-checks.ps1 -SkipTests

# Skip coverage analysis
.\tools\powershell\local-quality-checks.ps1 -SkipCoverage

# Combine multiple skips
.\tools\powershell\local-quality-checks.ps1 -SkipCoverage -SkipTypeCheck
```

### Parameters

- `-SkipLint`: Skip flake8 linting checks
- `-SkipTypeCheck`: Skip MyPy type checking
- `-SkipTests`: Skip unit tests
- `-SkipCoverage`: Skip code coverage analysis
- `-Verbose`: Enable verbose output (currently unused, reserved for future use)

## Output

The script provides clean output with clear status indicators:

- `[PASS]` - Check passed successfully
- `[FAIL]` - Check failed
- `[ERROR]` - Check encountered an error
- `[SKIP]` - Check was skipped

## Exit Codes

- `0`: All enabled quality checks passed
- `1`: One or more quality checks failed

## Prerequisites

- **PowerShell 5.1+** or **PowerShell Core 7.x**
- **Python 3.11+** (same as CI/CD)
- **Git repository** (script must be run from project root)

## Directory Structure

The script expects to be run from the project root and will automatically:
- Install dependencies in the current Python environment
- Run tests from the `backend/` directory
- Perform linting and type checking on the entire project

## Troubleshooting

### Common Issues

1. **Execution Policy Error**
   ```
   Solution: Use -ExecutionPolicy Bypass flag
   powershell -ExecutionPolicy Bypass -File .\tools\powershell\local-quality-checks.ps1
   ```

2. **Python Not Found**
   ```
   Solution: Ensure Python 3.11+ is installed and in PATH
   ```

3. **Module Not Found Errors**
   ```
   Solution: The script automatically installs dependencies, but ensure you're in the correct directory
   ```

4. **Tests Show 0 Results**
   ```
   Solution: The script uses the exact same command as CI/CD. If you see 0 tests, ensure you're running from the project root directory.
   ```

## Integration

### Pre-commit Hook
You can integrate this script as a pre-commit hook by adding it to your Git hooks:

```bash
# .git/hooks/pre-commit
#!/bin/sh
powershell -ExecutionPolicy Bypass -File ./tools/powershell/local-quality-checks.ps1
```

### IDE Integration
Most IDEs can be configured to run this script as a build task or external tool.

## Comparison with CI/CD

This script replicates the exact same checks as the GitHub Actions workflow:

| CI/CD Job | Local Script Equivalent | Notes |
|-----------|-------------------------|--------|
| `lint` | Flake8 + MyPy sections | Same ignore rules and flags |
| `test` | Unit Tests section | Same test discovery pattern |
| `coverage` | Code Coverage section | Same 80% threshold |
| `build-artifacts` | Not included | Build artifacts are CI/CD specific |

## Contributing

When modifying this script:

1. Ensure it stays in sync with `.github/workflows/ci-cd.yaml`
2. Test on both PowerShell 5.1 and PowerShell Core
3. Maintain backwards compatibility with existing parameters
4. Update this README when adding new features