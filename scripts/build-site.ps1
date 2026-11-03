# Build the showcase site into _site/ and refresh the README results table.
# Preview: python -m http.server 8090 --directory _site
$root = Split-Path -Parent $PSScriptRoot
python (Join-Path $root "scripts/build_site.py") --readme @args
exit $LASTEXITCODE
