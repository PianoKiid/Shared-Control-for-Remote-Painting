$taskRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskDocx = Join-Path $taskRoot 'results\phase_learning\LOPO_Results_APA_Figures_and_Table.docx'
$taskPdf = Join-Path $taskRoot 'results\phase_learning\final_lopo\results\tolerant_3s\LOPO_Results_APA_Figures_and_Table.pdf'
$taskRenderDir = Split-Path -Parent $taskPdf
New-Item -ItemType Directory -Path $taskRenderDir -Force | Out-Null

$taskWord = New-Object -ComObject Word.Application
$taskWord.Visible = $false
$taskWord.DisplayAlerts = 0
Write-Output 'WORD_CREATED'
try {
    $taskDocument = $taskWord.Documents.Open($taskDocx, $false, $true)
    Write-Output 'DOCUMENT_OPENED'
    $taskDocument.SaveAs2($taskPdf, 17)
    Write-Output 'PDF_EXPORTED'
    $taskDocument.Close($false)
}
finally {
    $taskWord.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($taskWord) | Out-Null
}

Write-Output $taskPdf
