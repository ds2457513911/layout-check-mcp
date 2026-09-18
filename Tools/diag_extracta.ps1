$dbg = "C:\Users\ds245\Documents\Project_Layout\_extracta_debug"
New-Item -ItemType Directory -Force -Path $dbg | Out-Null

$cdsroot = "D:\Dev_tools\Cadence_17.2\Cadence\Cadence_SPB_17.2-2016"
$env:CDSROOT = $cdsroot
$env:PATH = "$cdsroot\tools\bin;$cdsroot\tools\pcb\bin;$env:PATH"

$dra = "C:\Users\ds245\Documents\Work_Bmorn\Layout\footprint\3S48000163\nb_xtal4_3d2x2d5x0d7.dra"
$view = "C:\Users\ds245\Documents\Project_Layout\services\extracta_views\footprint_views.txt"

& "$cdsroot\tools\bin\extracta.exe" $dra $view "$dbg\pins.txt" "$dbg\pads.txt" "$dbg\geom.txt"

foreach ($f in "pins","pads","geom") {
    $p = "$dbg\$f.txt"
    if (Test-Path $p) {
        $n = (Get-Content $p).Count
        Write-Host "$f.txt : $n lines"
    } else {
        Write-Host "$f.txt : not found"
    }
}