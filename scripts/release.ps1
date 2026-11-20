<#
.SYNOPSIS
  Publish a new NET Sniffer version: bump version, test, build Windows locally, publish the GitHub
  release (which triggers the macOS/Linux builds) and delete every previous version locally and on GitHub.

.EXAMPLE
  .\scripts\release.ps1               # patch bump  1.0.0 -> 1.0.1
  .\scripts\release.ps1 -Bump minor   # 1.0.1 -> 1.1.0
  .\scripts\release.ps1 -Version 2.0.0
#>
param(
  [ValidateSet("patch", "minor", "major")] [string]$Bump = "patch",
  [string]$Version = "",
  [string]$Notes = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------- preflight
gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Run 'gh auth login' first." }
$Repo = (& $Py -c "import netsniffer.config as c; print(c.REPO)").Trim()
if (git status --porcelain --untracked-files=no) { Write-Host "Uncommitted changes will be included in the release commit." -ForegroundColor Yellow }

# ---------------------------------------------------------------- version
$InitFile = Join-Path $Root "netsniffer\__init__.py"
$src = Get-Content $InitFile -Raw
$cur = [regex]::Match($src, '__version__ = "(\d+)\.(\d+)\.(\d+)"')
if (-not $cur.Success) { throw "version not found" }
if (-not $Version) {
  $ma = [int]$cur.Groups[1].Value; $mi = [int]$cur.Groups[2].Value; $pa = [int]$cur.Groups[3].Value
  switch ($Bump) { "major" { $ma++; $mi = 0; $pa = 0 } "minor" { $mi++; $pa = 0 } default { $pa++ } }
  $Version = "$ma.$mi.$pa"
}
$Tag = "v$Version"
Step "Releasing $Tag to $Repo"
$src = $src -replace '__version__ = "[^"]+"', "__version__ = `"$Version`""
[System.IO.File]::WriteAllText($InitFile, $src, (New-Object System.Text.UTF8Encoding $false))

# ---------------------------------------------------------------- test & build
Step "Tests"
& $Py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed" }

Step "Building Windows installer (old builds are wiped first)"
& $Py scripts\build.py
if ($LASTEXITCODE -ne 0) { throw "build failed" }
$Exe = Join-Path $Root "dist\NETSniffer-Setup-Windows-x64.exe"

# ---------------------------------------------------------------- git
Step "Commit & tag"
git add -A
git commit -m "release: $Tag" | Out-Null
git tag -f $Tag
git push origin HEAD
git push origin $Tag --force

# ---------------------------------------------------------------- GitHub release
Step "Publishing release (triggers macOS & Linux builds)"
if (-not $Notes) {
  $prev = git tag --sort=-creatordate | Where-Object { $_ -ne $Tag } | Select-Object -First 1
  $range = if ($prev) { "$prev..$Tag" } else { $Tag }
  $Notes = (git log $range --pretty=format:"- %s" --no-merges | Where-Object { $_ -notmatch "^- release:" }) -join "`n"
  if (-not $Notes) { $Notes = "- Maintenance release" }
}
$NotesFile = New-TemporaryFile
[System.IO.File]::WriteAllText($NotesFile, $Notes, (New-Object System.Text.UTF8Encoding $false))
gh release create $Tag $Exe --repo $Repo --title "NET Sniffer $Version" --notes-file $NotesFile --latest
Remove-Item $NotesFile

# ---------------------------------------------------------------- never keep old versions
Step "Deleting previous releases, tags and workflow runs on GitHub"
$tags = gh release list --repo $Repo --limit 200 --json tagName -q ".[].tagName"
foreach ($t in $tags) { if ($t -and $t -ne $Tag) { gh release delete $t --repo $Repo --cleanup-tag --yes } }
foreach ($t in (git tag)) { if ($t -ne $Tag) { git tag -d $t | Out-Null; git push origin ":refs/tags/$t" 2>$null } }
$runs = gh run list --repo $Repo --limit 500 --json databaseId,status,headBranch -q '.[] | select(.status == "completed") | .databaseId'
foreach ($id in $runs) { if ($id) { gh run delete $id --repo $Repo | Out-Null } }

Step "Done: $Tag published. macOS & Linux builds are running in GitHub Actions:"
Write-Host "  https://github.com/$Repo/actions"
Write-Host "  https://github.com/$Repo/releases/latest"
