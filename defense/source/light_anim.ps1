# Adds the motion of the light deck with PowerPoint itself, so the file holds the animation XML
# that PowerPoint writes (WPS reads it the same way): a smooth fade between all slides, simple
# fades on click from light_anim.json, and the hidden flag of the backup slides. Also exports
# the PDF backup (hidden slides left out).
#   powershell -File light_anim.ps1 -In raw.pptx -Out deck.pptx [-Pdf deck.pdf]
param([string]$In, [string]$Out, [string]$Pdf = '', [string]$Spec = (Join-Path $PSScriptRoot 'light_anim.json'))
$ErrorActionPreference = 'Stop'
$cfg = Get-Content $Spec -Raw -Encoding UTF8 | ConvertFrom-Json
$app = New-Object -ComObject PowerPoint.Application
$p = $app.Presentations.Open((Resolve-Path $In).Path, $false, $false, $false)
try {
  foreach ($s in $p.Slides) {
    $s.SlideShowTransition.EntryEffect = 3849   # ppEffectFadeSmoothly
    $s.SlideShowTransition.Duration = 0.6
  }
  $n = 0
  foreach ($entry in $cfg.slides) {
    $sl = $p.Slides.Item([int]$entry.index)
    if ($entry.hidden) { $sl.SlideShowTransition.Hidden = -1 }
    $seq = $sl.TimeLine.MainSequence
    foreach ($grp in @($entry.clicks)) {
      $first = $true
      foreach ($name in @($grp.names)) {
        $shape = $sl.Shapes.Item([string]$name)
        $trigger = if ($first) { 1 } else { 2 }  # msoAnimTriggerOnPageClick, then WithPrevious
        $fx = $seq.AddEffect($shape, 10, 0, $trigger)  # msoAnimEffectFade, as one object
        $fx.Timing.Duration = 0.4
        $first = $false
      }
      $n++
    }
  }
  $p.SaveAs($Out)
  if ($Pdf) { $p.SaveAs($Pdf, 32) }
  "slides $($p.Slides.Count), click groups $n"
} finally {
  $p.Close()
  if ($app.Presentations.Count -eq 0) { $app.Quit() }
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}
