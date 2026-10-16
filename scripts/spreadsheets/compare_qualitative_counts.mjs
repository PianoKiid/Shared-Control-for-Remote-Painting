import { projectPath } from "../project_paths.mjs";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const oldPath = projectPath("data/spreadsheets/source_snapshots/input_backup_before_sub12-14.xlsx");
const newPath = projectPath("results/spreadsheets/인터뷰 정리_0728 - 복사본.xlsx");

const oldBook = await SpreadsheetFile.importXlsx(await FileBlob.load(oldPath));
const newBook = await SpreadsheetFile.importXlsx(await FileBlob.load(newPath));
const oldSheet = oldBook.worksheets.getItem("Code Counting");
const newSheet = newBook.worksheets.getItem("Code Counting");

const normalize = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
const expand = (value) => normalize(value).replace("S01~S07", "S01, S02, S03, S04, S05, S06, S07");
const parseCountCell = (value) => {
  const text = String(value ?? "");
  const total = Number(text.match(/Total Count\s*:\s*(\d+)/)?.[1] ?? 0);
  const parseLine = (label) => {
    const line = text.split("\n").find((x) => x.startsWith(`${label} :`));
    if (!line || line.trim().endsWith(": -")) return [];
    return expand(line.split(":").slice(1).join(":")).split(",").map((x) => x.trim()).filter(Boolean);
  };
  return { total, positive: parseLine("Positive"), negative: parseLine("Negative") };
};

const interfaces = oldSheet.getRange("D1:G1").values[0].map(normalize);
const codes = newSheet.getRange("C2:C10").values.flat().map(normalize);
const oldCounts = oldSheet.getRange("D2:G10").values;
const newCounts = newSheet.getRange("D2:G10").values;

const interfaceSummary = interfaces.map((name, col) => {
  const oldParsed = oldCounts.map((row) => parseCountCell(row[col]));
  const newParsed = newCounts.map((row) => parseCountCell(row[col]));
  return {
    interface: name,
    oldCodeMentions: oldParsed.reduce((sum, x) => sum + x.total, 0),
    newCodeMentions: newParsed.reduce((sum, x) => sum + x.total, 0),
    oldPositive: oldParsed.reduce((sum, x) => sum + x.positive.length, 0),
    newPositive: newParsed.reduce((sum, x) => sum + x.positive.length, 0),
    oldNegative: oldParsed.reduce((sum, x) => sum + x.negative.length, 0),
    newNegative: newParsed.reduce((sum, x) => sum + x.negative.length, 0),
  };
});

const codeDeltas = [];
for (let r = 0; r < codes.length; r++) {
  for (let c = 0; c < interfaces.length; c++) {
    const before = parseCountCell(oldCounts[r][c]);
    const after = parseCountCell(newCounts[r][c]);
    if (before.total !== after.total || before.positive.length !== after.positive.length || before.negative.length !== after.negative.length) {
      codeDeltas.push({
        code: codes[r], interface: interfaces[c],
        total: `${before.total}->${after.total}`,
        positive: `${before.positive.length}->${after.positive.length}`,
        negative: `${before.negative.length}->${after.negative.length}`,
        addedPositive: after.positive.filter((x) => !before.positive.includes(x)),
        addedNegative: after.negative.filter((x) => !before.negative.includes(x)),
      });
    }
  }
}

const taskCodes = newSheet.getRange("C13:C21").values.flat().map(normalize);
const taskBefore = oldSheet.getRange("D13:D21").values.flat().map((x) => expand(x).split(",").map((v) => v.trim()).filter(Boolean));
const taskAfter = newSheet.getRange("D13:D21").values.flat().map((x) => expand(x).split(",").map((v) => v.trim()).filter(Boolean));
const taskSummary = taskCodes.map((code, i) => ({
  code,
  oldCount: taskBefore[i].length,
  newCount: taskAfter[i].length,
  added: taskAfter[i].filter((x) => !taskBefore[i].includes(x)),
}));

console.log(JSON.stringify({ interfaceSummary, codeDeltas, taskSummary }, null, 2));
