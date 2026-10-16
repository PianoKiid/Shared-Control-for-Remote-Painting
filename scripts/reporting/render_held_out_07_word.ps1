$taskRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskDocx = Join-Path $taskRoot 'results\phase_learning\final_lopo\held_out_07_report\Held_Out_07_LOPO_APA_Table.docx'
$taskPdf = Join-Path $taskRoot 'results\phase_learning\final_lopo\held_out_07_report\Held_Out_07_LOPO_APA_Table.pdf'
$taskRenderDir = Split-Path -Parent $taskPdf
New-Item -ItemType Directory -Path $taskRenderDir -Force | Out-Null

$taskWord = New-Object -ComObject Word.Application
$taskWord.Visible = $false
$taskWord.DisplayAlerts = 0
try {
    $taskDocument = $taskWord.Documents.Open($taskDocx, $false, $true)
    $taskDocument.ExportAsFixedFormat($taskPdf, 17)
    $taskDocument.Close($false)
}
finally {
    $taskWord.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($taskWord) | Out-Null
}
Write-Output $taskPdf
