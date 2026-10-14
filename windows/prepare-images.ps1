param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Output,
    [int]$Size = 800
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$src = (Resolve-Path -LiteralPath $Source).Path
$out = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $out) { throw 'Output must be a new directory to avoid overwriting files.' }
if ($Size -lt 1 -or $Size -gt 10000) { throw 'Invalid image size.' }
New-Item -ItemType Directory -Path $out | Out-Null
$folders = @(Get-ChildItem -LiteralPath $src -Directory)
if (@(Get-ChildItem -LiteralPath $src -File | Where-Object Extension -Match '^\.(jpg|jpeg|png|webp)$').Count -gt 0) {
    $folders = @(Get-Item -LiteralPath $src)
}
$manifest = @()
foreach ($folder in $folders) {
    $files = @(Get-ChildItem -LiteralPath $folder.FullName -File | Where-Object Extension -Match '^\.(jpg|jpeg|png)$' | Sort-Object @{Expression={if ($_.Name.Contains('前')) {0} else {1}}}, Name)
    if ($files.Count -eq 0) { continue }
    $dest = Join-Path $out $folder.Name
    New-Item -ItemType Directory -Path $dest | Out-Null
    for ($i=0; $i -lt $files.Count; $i++) {
        Copy-Item -LiteralPath $files[$i].FullName -Destination (Join-Path $dest ('{0:D2}_{1}' -f ($i+1), $files[$i].Name))
    }
    $image = [Drawing.Image]::FromFile($files[0].FullName)
    try {
        $side = [Math]::Min($image.Width, $image.Height)
        $rect = [Drawing.Rectangle]::new([int][Math]::Floor(($image.Width-$side)/2), [int][Math]::Floor(($image.Height-$side)/2), $side, $side)
        $bitmap = [Drawing.Bitmap]::new($Size, $Size)
        try {
            $graphics = [Drawing.Graphics]::FromImage($bitmap)
            try {
                $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.DrawImage($image, [Drawing.Rectangle]::new(0,0,$Size,$Size), $rect, [Drawing.GraphicsUnit]::Pixel)
            } finally { $graphics.Dispose() }
            $bitmap.Save((Join-Path $dest ('素材图_{0}x{0}.jpg' -f $Size)), [Drawing.Imaging.ImageFormat]::Jpeg)
        } finally { $bitmap.Dispose() }
    } finally { $image.Dispose() }
    $manifest += [PSCustomObject]@{sku=$folder.Name; main_image=$files[0].Name; images=@($files.Name); material_size=$Size}
}
if ($manifest.Count -eq 0) { throw 'No JPG/PNG images found. Source should be a SKU folder or the parent of SKU folders.' }
ConvertTo-Json -InputObject $manifest -Depth 5 | Set-Content -LiteralPath (Join-Path $out 'manifest.json') -Encoding UTF8
Write-Host ('Prepared {0} SKU folders. Originals unchanged. Center crops require visual review.' -f $manifest.Count)
