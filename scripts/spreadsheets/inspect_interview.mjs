import { projectPath } from "../project_paths.mjs";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "D:/SNUCEM/PROJECTS/다부처/원격도장작업실험/DATA/Interview/인터뷰 정리_0728 - 복사본.xlsx";
const renderDir = projectPath(".cache/document_previews/spreadsheets/baseline");

const blob = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(blob);
const overview = await workbook.inspect({
  kind: "workbook,sheet,table,definedName,drawing",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 12,
  tableMaxCellChars: 120,
});
console.log("OVERVIEW\n" + overview.ndjson);

await fs.mkdir(renderDir, { recursive: true });
for (let i = 0; i < workbook.worksheets.items.length; i++) {
  const sheet = workbook.worksheets.getItemAt(i);
  const used = sheet.getUsedRange();
  const values = used ? used.values : [];
  const formulas = used ? used.formulas : [];
  console.log(`SHEET ${i}: ${sheet.name}`);
  console.log(JSON.stringify({ values, formulas }, null, 2));
  if (!sheet.name.toLowerCase().includes("old")) {
    const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 1, format: "png" });
    const safeName = `${String(i + 1).padStart(2, "0")}_${sheet.name.replace(/[\\/:*?"<>|]/g, "_")}.png`;
    await fs.writeFile(path.join(renderDir, safeName), new Uint8Array(await preview.arrayBuffer()));
  }
}
