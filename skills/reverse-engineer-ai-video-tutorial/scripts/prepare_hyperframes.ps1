param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
$script = Join-Path $PSScriptRoot "prepare_hyperframes.py"
& python $script @Arguments
exit $LASTEXITCODE
