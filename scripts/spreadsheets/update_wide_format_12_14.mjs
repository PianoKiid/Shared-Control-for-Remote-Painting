import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const metricsPath = process.argv[2];
if (!metricsPath) throw new Error("wide_format_metrics.json 경로가 필요합니다.");

const payload = JSON.parse(await fs.readFile(metricsPath, "utf8"));
const sourcePath = payload.source_workbook;
const outputPath = payload.output_workbook;
const blob = await FileBlob.load(sourcePath);
const workbook = await SpreadsheetFile.importXlsx(blob);
const sheet = workbook.worksheets.getItem("WIDE");
if (!sheet) throw new Error("WIDE 시트를 찾지 못했습니다.");

const used = sheet.getUsedRange();
const values = used?.values ?? [];
const rowBySubject = new Map();
for (let i = 1; i < values.length; i++) {
  const id = Number(values[i]?.[0]);
  if (Number.isFinite(id)) rowBySubject.set(id, i + 1);
}

const conditionOffset = { MS: 0, MP: 1, VS: 2, VP: 3 };
const metricStartColumn = {
  average_work_distance_m: 26, // Z
  average_work_speed_m_s: 30,  // AD
  average_move_distance_m: 34, // AH
  average_move_speed_m_s: 38,  // AL
};

function columnName(index) {
  let n = index, out = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    out = String.fromCharCode(65 + r) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

let written = 0;
for (const trial of payload.trials) {
  if (!trial.complete) continue;
  const row = rowBySubject.get(Number(trial.subject));
  const offset = conditionOffset[trial.interface];
  if (!row || offset === undefined) continue;
  for (const [metric, startColumn] of Object.entries(metricStartColumn)) {
    const value = trial[metric];
    if (value === null || value === undefined || !Number.isFinite(Number(value))) continue;
    const cell = `${columnName(startColumn + offset)}${row}`;
    sheet.getRange(cell).values = [[Number(value)]];
    sheet.getRange(cell).format.numberFormat = "0.000000";
    written++;
  }
}

workbook.recalculate();
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({ sourcePath, outputPath, completedTrials: payload.trials.filter(t => t.complete).length, writtenCells: written }));
