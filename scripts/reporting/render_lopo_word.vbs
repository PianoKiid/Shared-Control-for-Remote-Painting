Option Explicit

Dim fso, taskRoot, taskDocx, taskPdf, wordApp, wordDoc
Set fso = CreateObject("Scripting.FileSystemObject")
taskRoot = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
taskDocx = fso.BuildPath(taskRoot, "results\phase_learning\final_lopo\results\tolerant_3s\LOPO_Results_APA_Figures_Table_and_Timeline.docx")
taskPdf = fso.BuildPath(taskRoot, "results\phase_learning\final_lopo\results\tolerant_3s\LOPO_Results_APA_Figures_Table_and_Timeline.pdf")

WScript.Echo "START"
Set wordApp = CreateObject("Word.Application")
wordApp.Visible = False
wordApp.DisplayAlerts = 0
WScript.Echo "WORD_CREATED"
Set wordDoc = wordApp.Documents.Open(taskDocx, False, True)
WScript.Echo "DOCUMENT_OPENED"
wordDoc.ExportAsFixedFormat taskPdf, 17
WScript.Echo "PDF_EXPORTED"
wordDoc.Close False
wordApp.Quit
Set wordDoc = Nothing
Set wordApp = Nothing
WScript.Echo taskPdf
