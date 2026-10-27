@echo off
setlocal
cd /d "%~dp0"

git rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 (
    echo ERROR: This folder is not inside a Git repository.
    pause
    exit /b 1
)

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if not defined BRANCH (
    echo ERROR: Git is in detached HEAD state. Switch to a branch before publishing.
    pause
    exit /b 1
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo ERROR: No Git remote named "origin" is configured.
    pause
    exit /b 1
)

git diff --cached --quiet
if errorlevel 1 (
    echo ERROR: There are already staged changes.
    echo Commit or unstage them before running this script.
    pause
    exit /b 1
)

echo Removing local-only and development files from the GitHub version...
git rm -r --cached --ignore-unmatch -- .vscode
if errorlevel 1 goto :failed
git rm --cached --ignore-unmatch -- bootstrap_*.py fix_*.py .env
if errorlevel 1 goto :failed

echo Staging the project source, tests, documentation, and configuration...
git add -A -- .gitignore .gitattributes .env.example README.md pyproject.toml app tests publish_to_github.bat
if errorlevel 1 goto :failed

git diff --cached --quiet
if not errorlevel 1 (
    echo There are no changes to publish.
    pause
    exit /b 0
)

echo.
echo Changes prepared for publishing:
git diff --cached --stat
echo.
git diff --cached --name-status
echo.
choice /C YN /M "Review the list above. Commit and push these changes to origin/%BRANCH%"
if errorlevel 2 (
    git reset --quiet
    echo Cancelled. Changes were left in your files and unstaged.
    pause
    exit /b 0
)

git commit -m "Prepare public repository" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
if errorlevel 1 goto :failed

git push -u origin "%BRANCH%"
if errorlevel 1 (
    echo ERROR: The commit was created, but the push failed.
    echo Check your network, GitHub credentials, and remote branch status.
    pause
    exit /b 1
)

echo.
echo Publish completed successfully.
pause
exit /b 0

:failed
echo.
echo ERROR: A Git command failed. Review the output above before continuing.
pause
exit /b 1
