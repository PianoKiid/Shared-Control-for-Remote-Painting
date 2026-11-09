param(
    [Parameter(Mandatory=$true)][string]$IsaacPython,
    [ValidateSet('manual','probability','shared')][string]$Condition = 'shared',
    [ValidateSet('haply','scripted','replay')][string]$InputMode = 'haply',
    [string]$Replay = '',
    [string]$Config = '',
    [switch]$Headless
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $IsaacPython -PathType Leaf)) {
    throw "Isaac Sim python.bat was not found: $IsaacPython"
}
$teleopScript = Join-Path $PSScriptRoot 'teleop.py'
$teleopArgs = @($teleopScript, 'isaac', '--condition', $Condition, '--input', $InputMode)
if ($Replay) { $teleopArgs += @('--replay', $Replay) }
if ($Config) { $teleopArgs += @('--config', $Config) }
if ($Headless) { $teleopArgs += '--headless' }
& $IsaacPython @teleopArgs
exit $LASTEXITCODE
