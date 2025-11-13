#!/usr/bin/env pwsh
# Local Quality Checks Script
# Replicates the CI/CD pipeline quality checks locally for Windows development
# Based on .github/workflows/ci-cd.yaml

param(
    [switch]$SkipLint,
    [switch]$SkipTests,
    [switch]$SkipCoverage,
    [switch]$SkipTypeCheck,
    [switch]$Verbose
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Function to write output
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = ""
    )
    Write-Host $Message
}

# Function to write section headers
function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "  $Title"
    Write-Host ("=" * 60)
}

# Function to check if a command exists
function Test-CommandExists {
    param([string]$Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    return $?
}

# Function to run a command and capture output
function Invoke-QualityCheck {
    param(
        [string]$Command,
        [string]$Arguments,
        [string]$WorkingDirectory = $PWD,
        [string]$CheckName
    )
    
    Write-Host "Running: $Command $Arguments"
    
    try {
        $process = Start-Process -FilePath $Command -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -Wait -PassThru -NoNewWindow
        
        if ($process.ExitCode -eq 0) {
            Write-Host "[PASS] $CheckName - PASSED"
            return $true
        } else {
            Write-Host "[FAIL] $CheckName - FAILED (Exit code: $($process.ExitCode))"
            return $false
        }
    } catch {
        Write-Host "[ERROR] $CheckName - ERROR - $($_.Exception.Message)"
        return $false
    }
}

# Main script execution
try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
    Set-Location $projectRoot

    Write-ColorOutput "*** Starting Local Quality Checks for Advanced Task Manager ***" -Color $Blue
    Write-ColorOutput "Project Root: $projectRoot" -Color $Yellow
    Write-ColorOutput "Python Version: $(python --version 2>&1)" -Color $Yellow
    
    $allPassed = $true
    $checkResults = @()

    # ========================================
    # DEPENDENCY INSTALLATION
    # ========================================
    Write-Section "Installing Dependencies"
    
    Write-ColorOutput "Upgrading pip..." -Color $Yellow
    $pipUpgrade = Invoke-QualityCheck -Command "python" -Arguments "-m pip install --upgrade pip" -CheckName "Pip Upgrade"
    if (-not $pipUpgrade) { $allPassed = $false }

    # Install linting dependencies
    if (-not $SkipLint -or -not $SkipTypeCheck) {
        Write-ColorOutput "Installing linting dependencies..." -Color $Yellow
        $lintDeps = Invoke-QualityCheck -Command "pip" -Arguments "install flake8 mypy" -CheckName "Lint Dependencies"
        if (-not $lintDeps) { $allPassed = $false }
    }

    # Install project dependencies
    if (-not $SkipTests -or -not $SkipCoverage) {
        Write-ColorOutput "Installing project dependencies..." -Color $Yellow
        $projectDeps = Invoke-QualityCheck -Command "pip" -Arguments "install -r requirements.txt" -CheckName "Project Dependencies"
        if (-not $projectDeps) { $allPassed = $false }
    }

    # Install coverage if needed
    if (-not $SkipCoverage) {
        Write-ColorOutput "Installing coverage..." -Color $Yellow
        $coverageDep = Invoke-QualityCheck -Command "pip" -Arguments "install coverage" -CheckName "Coverage Dependency"
        if (-not $coverageDep) { $allPassed = $false }
    }

    # ========================================
    # LINTING
    # ========================================
    if (-not $SkipLint) {
        Write-Section "Code Linting with Flake8"
        
        $flakeResult = Invoke-QualityCheck -Command "flake8" -Arguments "--ignore=E501,E266,W293 ." -CheckName "Flake8 Linting"
        $checkResults += @{ Name = "Flake8 Linting"; Passed = $flakeResult }
        if (-not $flakeResult) { $allPassed = $false }
    } else {
        Write-ColorOutput "[SKIP] Skipping linting checks" -Color $Yellow
    }

    # ========================================
    # TYPE CHECKING
    # ========================================
    if (-not $SkipTypeCheck) {
        Write-Section "Type Checking with MyPy"
        
        $mypyResult = Invoke-QualityCheck -Command "mypy" -Arguments "backend/src/ --strict --ignore-missing-imports --show-error-codes --warn-unused-ignores" -CheckName "MyPy Type Checking"
        $checkResults += @{ Name = "MyPy Type Checking"; Passed = $mypyResult }
        if (-not $mypyResult) { $allPassed = $false }
    } else {
        Write-ColorOutput "[SKIP] Skipping type checking" -Color $Yellow
    }

    # ========================================
    # UNIT TESTS
    # ========================================
    if (-not $SkipTests) {
        Write-Section "Running Unit Tests"
        
        $testResult = Invoke-QualityCheck -Command "python" -Arguments "-m unittest discover -s tests -p `"*_test.py`"" -WorkingDirectory "$projectRoot/backend" -CheckName "Unit Tests"
        $checkResults += @{ Name = "Unit Tests"; Passed = $testResult }
        if (-not $testResult) { $allPassed = $false }
    } else {
        Write-ColorOutput "[SKIP] Skipping unit tests" -Color $Yellow
    }

    # ========================================
    # CODE COVERAGE
    # ========================================
    if (-not $SkipCoverage) {
        Write-Section "Code Coverage Analysis"
        
        Write-ColorOutput "Running tests with coverage..." -Color $Yellow
        $coverageRun = Invoke-QualityCheck -Command "coverage" -Arguments "run -m unittest discover -s tests -p `"*_test.py`"" -WorkingDirectory "$projectRoot/backend" -CheckName "Coverage Run"
        
        if ($coverageRun) {
            Write-ColorOutput "Generating coverage report..." -Color $Yellow
            $coverageReport = Invoke-QualityCheck -Command "coverage" -Arguments "report -m" -WorkingDirectory "$projectRoot/backend" -CheckName "Coverage Report"
            
            Write-ColorOutput "Checking coverage threshold (80%)..." -Color $Yellow
            $coverageThreshold = Invoke-QualityCheck -Command "coverage" -Arguments "report --fail-under=80" -WorkingDirectory "$projectRoot/backend" -CheckName "Coverage Threshold"
            
            $checkResults += @{ Name = "Code Coverage"; Passed = ($coverageRun -and $coverageReport -and $coverageThreshold) }
            if (-not ($coverageRun -and $coverageReport -and $coverageThreshold)) { $allPassed = $false }
        } else {
            $checkResults += @{ Name = "Code Coverage"; Passed = $false }
            $allPassed = $false
        }
    } else {
        Write-ColorOutput "[SKIP] Skipping coverage analysis" -Color $Yellow
    }

    # ========================================
    # SUMMARY REPORT
    # ========================================
    Write-Section "Quality Checks Summary"
    
    foreach ($result in $checkResults) {
        $status = if ($result.Passed) { "[PASS] PASSED" } else { "[FAIL] FAILED" }
        $color = if ($result.Passed) { $Green } else { $Red }
        Write-ColorOutput "  $($result.Name): $status" -Color $color
    }
    
    Write-Host ""
    if ($allPassed) {
        Write-ColorOutput "*** All quality checks PASSED! Ready for commit/push. ***" -Color $Green
        exit 0
    } else {
        Write-ColorOutput "*** Some quality checks FAILED! Please fix issues before committing. ***" -Color $Red
        exit 1
    }

} catch {
    Write-ColorOutput "*** Script execution failed: $($_.Exception.Message) ***" -Color $Red
    Write-ColorOutput "Stack trace: $($_.ScriptStackTrace)" -Color $Red
    exit 1
}