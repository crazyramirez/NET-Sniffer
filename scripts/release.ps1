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
# Native tools (PyInstaller, git, gh) log progress to stderr; Windows PowerShell 5.1 would treat that as a
# fatal error under "Stop". Failures are detected through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
function Check($what) { if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $what" -ForegroundColor Red; exit 1 } }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------- preflight
gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Run 'gh auth login' first." -ForegroundColor Red; exit 1 }
$Repo = (& $Py -c "import netsniffer.config as c; print(c.REPO)").Trim()
if (git status --porcelain --untracked-files=no) { Write-Host "Uncommitted changes will be included in the release commit." -ForegroundColor Yellow }

# ---------------------------------------------------------------- version
$InitFile = Join-Path $Root "netsniffer\__init__.py"
$src = Get-Content $InitFile -Raw
$cur = [regex]::Match($src, '__version__ = "(\d+)\.(\d+)\.(\d+)"')
if (-not $cur.Success) { Write-Host "version not found" -ForegroundColor Red; exit 1 }
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
Check "tests"

Step "Building Windows installer (old builds are wiped first)"
& $Py scripts\build.py
Check "build"
$Exe = Join-Path $Root "dist\NETSniffer-Setup-Windows-x64.exe"
if (-not (Test-Path $Exe)) { Write-Host "FAILED: installer not found" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- git
Step "Commit & tag"
git add -A
if (git status --porcelain) { git commit -q -m "release: $Tag"; Check "git commit" }
git tag -f $Tag
git push origin HEAD
Check "git push"
git push origin $Tag --force
Check "git push tag"

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
Check "gh release create"
Remove-Item $NotesFile

Step "Waiting for the macOS & Linux builds (GitHub Actions)"
Start-Sleep 10
$RunId = gh run list --repo $Repo --workflow release.yml --limit 1 --json databaseId -q ".[0].databaseId"
$CiOk = $false
if ($RunId) { gh run watch $RunId --repo $Repo --exit-status --interval 30 | Out-Null; $CiOk = ($LASTEXITCODE -eq 0) }
if (-not $CiOk) { Write-Host "GitHub Actions build failed: https://github.com/$Repo/actions/runs/$RunId" -ForegroundColor Red }

# ---------------------------------------------------------------- never keep old versions
# only once every installer of the new version exists: a failed build keeps the previous release available
if ($CiOk) {
  Step "Deleting previous releases, tags and workflow runs on GitHub"
  $tags = gh release list --repo $Repo --limit 200 --json tagName -q ".[].tagName"
  foreach ($t in $tags) { if ($t -and $t -ne $Tag) { gh release delete $t --repo $Repo --cleanup-tag --yes } }
  foreach ($t in (git tag)) { if ($t -ne $Tag) { git tag -d $t | Out-Null; git push origin ":refs/tags/$t" 2>$null } }
  $runs = (gh run list --repo $Repo --limit 500 --json databaseId,status | ConvertFrom-Json) |
    Where-Object { $_.status -eq "completed" -and "$($_.databaseId)" -ne "$RunId" }
  foreach ($r in $runs) { gh run delete $r.databaseId --repo $Repo | Out-Null }
} else {
  Write-Host "Previous releases kept because the new version is incomplete." -ForegroundColor Yellow
}

Step "Downloading every installer of $Tag into dist\"
gh release download $Tag --repo $Repo --dir (Join-Path $Root "dist") --clobber
Check "gh release download"
Get-ChildItem (Join-Path $Root "dist") | ForEach-Object { "  {0,-36} {1,7:N1} MB" -f $_.Name, ($_.Length / 1MB) }

Step "Done: $Tag published"
Write-Host "  https://github.com/$Repo/releases/latest"
