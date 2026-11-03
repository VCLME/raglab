# Build the raglab technical report on Windows (no make needed).
#   powershell -NoProfile -ExecutionPolicy Bypass -File docs\rapport\build.ps1
# Uses tectonic if installed, otherwise latexmk, otherwise two pdflatex passes.

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $doc = 'raglab-rapport'
    if (Get-Command tectonic -ErrorAction SilentlyContinue) {
        tectonic "$doc.tex"
    } elseif (Get-Command latexmk -ErrorAction SilentlyContinue) {
        latexmk -pdf -interaction=nonstopmode -halt-on-error "$doc.tex"
    } elseif (Get-Command pdflatex -ErrorAction SilentlyContinue) {
        # Two passes: the second one resolves the table of contents and references.
        pdflatex -interaction=nonstopmode -halt-on-error "$doc.tex"
        pdflatex -interaction=nonstopmode -halt-on-error "$doc.tex"
    } else {
        throw 'No LaTeX toolchain found: install tectonic, MiKTeX or TeX Live (see README.md).'
    }
    if ($LASTEXITCODE -ne 0) { throw "LaTeX build failed (exit code $LASTEXITCODE)." }
    Write-Output "Built $PSScriptRoot\$doc.pdf"
} finally {
    Pop-Location
}
