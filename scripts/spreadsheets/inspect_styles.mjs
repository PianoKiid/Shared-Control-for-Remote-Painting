import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "D:/SNUCEM/PROJECTS/다부처/원격도장작업실험/DATA/Interview/인터뷰 정리_0728 - 복사본.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
for (const [sheetId, range] of [["Code Counting", "A1:G3"], ["Code Quotation", "A1:G3"], ["Code Description", "A1:D3"]]) {
  const result = await workbook.inspect({ kind: "computedStyle", sheetId, range, maxChars: 8000 });
  console.log(`${sheetId} ${range}\n${result.ndjson}`);
}
