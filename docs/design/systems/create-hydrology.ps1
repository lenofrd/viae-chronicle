$dir = "f:\viae-chronicle\docs\design\systems\03-hydrology"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$files = @(
    "00-overview.md",
    "river-segments.md",
    "water-level.md",
    "crossing.md",
    "irrigation.md",
    "siltation.md"
)

foreach ($f in $files) {
    New-Item -ItemType File -Force -Path (Join-Path $dir $f) | Out-Null
}

Write-Host "Created $dir with $($files.Count) empty files."
Get-ChildItem $dir | Select-Object Name, Length | Format-Table -AutoSize
