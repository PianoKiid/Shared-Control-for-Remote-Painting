import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2];
const renderPath = process.argv[3];
const probeRange = process.argv[4];
if (!inputPath) throw new Error("검사할 xlsx 경로가 필요합니다.");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = workbook.worksheets.getItem("WIDE");
if (!sheet) throw new Error("WIDE 시트를 찾지 못했습니다.");
const report = await workbook.inspect({ kind: "workbook,sheet,table,formula,error", maxChars: 10000, tableMaxRows: 14, tableMaxCols: 45 });
console.log(report.ndjson);
if (probeRange) console.log(JSON.stringify({ probeRange, values: sheet.getRange(probeRange).values }));
if (renderPath) {
  await fs.mkdir(path.dirname(renderPath), { recursive: true });
  const image = await workbook.render({ sheetName: "WIDE", range: "A1:AO11", scale: 1.2, format: "png" });
  await fs.writeFile(renderPath, new Uint8Array(await image.arrayBuffer()));
}
