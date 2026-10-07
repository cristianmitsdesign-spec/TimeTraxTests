# Test lines for the Timetrax bridge, from the sample weekly sheet (Mon..Fri only).
# 1. Open Timetrax to a FUTURE week (not the current pay week), on the Direct page.
# 2. Check each project code below against Timetrax's Project List (suffix varies).
# 3. Run once as-is (dry run). Then add -live, then -live -save.
#
# Usage:  .\tt_test_lines.ps1            (dry run)
#         .\tt_test_lines.ps1 -live      (types into the grid, no save)
#         .\tt_test_lines.ps1 -live -save
#         .\tt_test_lines.ps1 -live -save -only 3   (just the 3rd line)

param([switch]$live, [switch]$save, [int]$only = 0)

$PY  = "c:\python314\python.exe"
$TT  = "$PSScriptRoot\tt_cell.py"
$ACT = "ME"     # activity code confirmed from the Activity list
# Project codes below are the FULL Timetrax codes. "-M" was confirmed for 1905-01;
# correct any line whose project is reported "Project Not Found".

$flags = @()
if ($live) { $flags += "--live" }
if ($save) { $flags += "--save" }

$lines = @(
  @("1905-01-M", "1-04", "tue=0.75", "thu=1.25", "fri=2"),
  @("2404-01-M", "1-04", "tue=0.75", "thu=1",    "fri=1"),
  @("2128-10-M", "1-05", "mon=0.5",  "tue=3.25", "wed=4",    "thu=0.5"),
  @("2430-04-M", "1-04", "mon=3",    "tue=0.25", "wed=1",    "thu=2.5", "fri=1"),
  @("2430-05-M", "1-03", "tue=0.25", "wed=0.5",  "thu=1"),
  @("2430-03-M", "1-03", "mon=1",    "tue=0.25", "wed=0.75", "thu=1.5"),
  @("2430-10-M", "1-03", "tue=0.25", "wed=0.5"),
  @("2428-03-M", "1-04", "tue=0.25"),
  @("2430-07-M", "1-03", "mon=1",    "tue=0.25", "wed=1"),
  @("2430-01-M", "1-04", "tue=0.25", "wed=0.25"),
  @("2430-35-M", "1-04", "mon=0.5",  "tue=0.25", "thu=0.25"),
  @("2430-06-M", "1-05", "fri=2"),
  @("2430-08-M", "1-03", "mon=1",    "tue=0.25", "fri=0.5")
  # Phase unreadable on the sheet ("1-0?"); fill in and uncomment:
  # ,@("1815-02-M", "1-0X", "tue=1", "fri=2.5")
)

$n = 0
foreach ($l in $lines) {
  $n++
  if ($only -ne 0 -and $only -ne $n) { continue }
  $proj = $l[0]
  $days = $l[2..($l.Length - 1)]
  Write-Host "`n--- line $n : $proj $($l[1]) $ACT $($days -join ' ') ---"
  & $PY $TT line auto $proj $l[1] $ACT @days @flags --page direct
  if ($LASTEXITCODE -ne 0) { Write-Host "stopped at line $n"; break }
}