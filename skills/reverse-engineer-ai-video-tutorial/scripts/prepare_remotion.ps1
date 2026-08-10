param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
$script = Join-Path $PSScriptRoot "prepare_remotion.py"
& python $script @Arguments
exit $LASTEXITCODE
