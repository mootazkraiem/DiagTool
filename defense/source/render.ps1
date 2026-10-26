param([string]$Pptx, [string]$OutDir, [int]$Width = 1600, [string]$Only = "")
New-Item -ItemType Directory -Force $OutDir | Out-Null
Get-ChildItem $OutDir -Filter "s*.png" | Remove-Item -Force
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($Pptx, $true, $false, $false)
$n = $pres.Slides.Count
$list = if ($Only) { $Only.Split(',') | ForEach-Object { [int]$_ } } else { 1..$n }
foreach ($i in $list) { $pres.Slides.Item($i).Export((Join-Path $OutDir ("s{0:D2}.png" -f $i)), "PNG", $Width, [int]($Width * 9 / 16)) }
$pres.Close()
if ($app.Presentations.Count -eq 0) { $app.Quit() }
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
"rendered $($list.Count) of $n"
