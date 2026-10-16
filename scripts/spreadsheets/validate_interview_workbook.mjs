import { projectPath } from "../project_paths.mjs";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = projectPath("data/spreadsheets/source_snapshots/input_backup_before_sub12-14.xlsx");
const outputPath = projectPath("results/spreadsheets/인터뷰 정리_0728 - 복사본.xlsx");
const renderDir = projectPath(".cache/document_previews/spreadsheets/final");

const source = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
const output = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));

function fail(message) {
  throw new Error(message);
}

function matrix(sheet, address) {
  return sheet.getRange(address).values;
}

const remapParticipantIds = (value) => String(value)
  .replace(/\bS12\b/g, "S08")
  .replace(/\bS13\b/g, "S09")
  .replace(/\bS14\b/g, "S10");

function sameUsedSheet(a, b, name) {
  const ar = a.worksheets.getItem(name).getUsedRange();
  const br = b.worksheets.getItem(name).getUsedRange();
  const av = { values: ar?.values ?? [], formulas: ar?.formulas ?? [] };
  const bv = { values: br?.values ?? [], formulas: br?.formulas ?? [] };
  if (JSON.stringify(av) !== JSON.stringify(bv)) fail(`${name} changed unexpectedly`);
}

const sheetNames = output.worksheets.items.map((s) => s.name);
const expectedSheets = ["Code Counting", "Code Description", "Code Quotation", "Old", "Coding Evidence"];
if (JSON.stringify(sheetNames) !== JSON.stringify(expectedSheets)) {
  fail(`Unexpected sheet order: ${sheetNames.join(", ")}`);
}
sameUsedSheet(source, output, "Code Description");
sameUsedSheet(source, output, "Old");

const expectedCounts = [
  ["Total Count : 4\nPositive : S02, S13\nNegative : S07, S12", "Total Count : 5\nPositive : S13\nNegative : S03, S05, S06, S07", "Total Count : 6\nPositive : S03, S06, S07, S13\nNegative : S04, S12", "Total Count : 4\nPositive : S06\nNegative : S01, S05, S07"],
  ["Total Count : 6\nPositive : S02, S04\nNegative : S01, S12, S13, S14", "Total Count : 4\nPositive : -\nNegative : S01, S06, S07, S14", "Total Count : 5\nPositive : S02, S13\nNegative : S06, S07, S14", "Total Count : 3\nPositive : S13\nNegative : S01, S07"],
  ["Total Count : 2\nPositive : -\nNegative : S03, S04", "Total Count : 2\nPositive : -\nNegative : S03, S04", "Total Count : 2\nPositive : -\nNegative : S04, S05", "Total Count : 1\nPositive : -\nNegative : S04"],
  ["Total Count : 3\nPositive : S02, S06\nNegative : S12", "Total Count : 3\nPositive : S02, S12\nNegative : S13", "Total Count : 8\nPositive : S02, S03\nNegative : S01, S04, S05, S06, S07, S12", "Total Count : 6\nPositive : S13, S14\nNegative : S03, S04, S05, S07"],
  ["Total Count : 7\nPositive : S02, S04, S12\nNegative : S03, S05, S06, S07", "Total Count : 3\nPositive : S13\nNegative : S03, S07", "Total Count : 7\nPositive : -\nNegative : S02, S04, S05, S07, S12, S13, S14", "Total Count : 5\nPositive : S14\nNegative : S01, S04, S05, S12"],
  ["Total Count : 3\nPositive : S12, S13, S14\nNegative : -", "Total Count : 4\nPositive : S02, S07\nNegative : S01, S03", "Total Count : 5\nPositive : -\nNegative : S01, S03, S07, S12, S14", "Total Count : 6\nPositive : S14\nNegative : S01, S02, S06, S07, S12"],
  ["Total Count : 0", "Total Count : 8\nPositive : S02, S04, S12, S13\nNegative : S01, S05, S06, S13, S14", "Total Count : 0", "Total Count : 6\nPositive : S01, S03, S13, S14\nNegative : S04, S06"],
  ["Total Count : 2\nPositive : -\nNegative : S06, S14", "Total Count : 1\nPositive : -\nNegative : S14", "Total Count : 5\nPositive : S01, S02, S06, S07\nNegative : S14", "Total Count : 5\nPositive : S01, S02, S12, S13, S14\nNegative : -"],
  ["Total Count : 10\nPositive : S02, S04, S06, S12\nNegative : S01, S03, S05, S07, S13, S14", "Total Count : 8\nPositive : -\nNegative : S01~S07, S14", "Total Count : 10\nPositive : S06, S13, S14\nNegative : S01, S02, S03, S04, S05, S07, S12", "Total Count : 9\nPositive : S02, S12, S13\nNegative : S01, S03, S04, S05, S06, S07"],
];
const mappedExpectedCounts = expectedCounts.map((row) => row.map(remapParticipantIds));
const counting = output.worksheets.getItem("Code Counting");
if (JSON.stringify(matrix(counting, "D2:G10")) !== JSON.stringify(mappedExpectedCounts)) fail("Count matrix mismatch");

const expectedTasks = [
  "S01, S03, S07, S08, S10", "S01, S07, S10", "S03, S05, S07, S08, S09, S10",
  "S03, S05, S07, S10", "S03, S05, S07, S08, S09, S10", "S01, S02, S04, S07, S09",
  "S02, S03, S04, S06, S07, S09, S10", "S01, S04, S07, S08, S09, S10", "S02, S08, S09, S10",
];
if (JSON.stringify(matrix(counting, "D13:D21").flat()) !== JSON.stringify(expectedTasks)) fail("Task participant list mismatch");

const evidenceSheet = output.worksheets.getItem("Coding Evidence");
const evidenceRows = matrix(evidenceSheet, "A2:I73");
if (evidenceRows.length !== 72 || evidenceRows.some((r) => r.length !== 9 || r.some((v) => v === null || v === undefined || String(v).trim() === ""))) {
  fail("Coding Evidence must contain 72 complete rows");
}
if (evidenceRows.some((r) => !["S08", "S09", "S10"].includes(String(r[0])))) fail("Unexpected participant in Coding Evidence");
const sourcePrefixByParticipant = { S08: "12-", S09: "13-", S10: "14-" };
if (evidenceRows.some((r) => !String(r[5]).startsWith(sourcePrefixByParticipant[r[0]]))) fail("Participant/source transcript mapping mismatch");

const interfaces = ["Monitor Stereo", "Monitor PCD", "VR Stereo", "VR PCD"];
const normalizeText = (value) => String(value).replace(/\s+/g, " ").trim();
const codes = matrix(counting, "C2:C10").flat().map(normalizeText);
const evidenceInterface = evidenceRows.filter((r) => r[2] === "Interface experience");
const parseParticipants = (text, label) => {
  const line = String(text).split("\n").find((x) => x.startsWith(`${label} :`));
  if (!line || line.endsWith(": -")) return new Set();
  const raw = line.split(":").slice(1).join(":").trim();
  const expanded = raw.replace("S01~S07", "S01, S02, S03, S04, S05, S06, S07");
  return new Set(expanded.split(",").map((x) => x.trim()).filter(Boolean));
};

for (let ci = 0; ci < codes.length; ci++) {
  for (let ii = 0; ii < interfaces.length; ii++) {
    const cell = mappedExpectedCounts[ci][ii];
    const positive = parseParticipants(cell, "Positive");
    const negative = parseParticipants(cell, "Negative");
    const rows = evidenceInterface.filter((r) => r[1] === interfaces[ii] && normalizeText(r[3]) === codes[ci]);
    for (const participant of ["S08", "S09", "S10"]) {
      const ep = rows.some((r) => r[0] === participant && r[4] === "Positive");
      const en = rows.some((r) => r[0] === participant && r[4] === "Negative");
      if (ep !== positive.has(participant) || en !== negative.has(participant)) {
        fail(`Evidence/count mismatch: ${participant} / ${interfaces[ii]} / ${codes[ci]}`);
      }
    }
  }
}

const evidenceTasks = evidenceRows.filter((r) => r[2] === "Task need / strategy");
const taskCodes = matrix(counting, "C13:C21").flat().map(normalizeText);
for (let i = 0; i < taskCodes.length; i++) {
  const listed = new Set(expectedTasks[i].split(",").map((x) => x.trim()));
  for (const participant of ["S08", "S09", "S10"]) {
    const hasEvidence = evidenceTasks.some((r) => r[0] === participant && normalizeText(r[3]) === taskCodes[i]);
    if (hasEvidence !== listed.has(participant)) fail(`Task evidence mismatch: ${participant} / ${taskCodes[i]}`);
  }
}

const participantFacingText = [
  ...matrix(counting, "D2:G10").flat(),
  ...matrix(counting, "D13:D21").flat(),
  ...matrix(output.worksheets.getItem("Code Quotation"), "D2:G19").flat(),
].filter((v) => v !== null && v !== undefined).join("\n");
if (/\bS(?:12|13|14)\b/.test(participantFacingText)) fail("Old participant IDs remain in counting or quotations");

const formulaErrors = [];
for (const sheet of output.worksheets.items) {
  const used = sheet.getUsedRange();
  if (!used) continue;
  for (const row of used.values ?? []) {
    for (const value of row) {
      if (typeof value === "string" && /#(?:REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!)/.test(value)) formulaErrors.push(`${sheet.name}: ${value}`);
    }
  }
}
if (formulaErrors.length) fail(`Formula errors: ${formulaErrors.join("; ")}`);

await fs.mkdir(renderDir, { recursive: true });
const renders = [
  ["Code Counting", "A1:G21", "01_Code Counting.png"],
  ["Code Quotation", "A1:G19", "02_Code Quotation.png"],
  ["Coding Evidence", "A1:I18", "03_Coding Evidence_start.png"],
  ["Coding Evidence", "A56:I73", "04_Coding Evidence_end.png"],
];
for (const [sheetName, range, filename] of renders) {
  const preview = await output.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(renderDir, filename), new Uint8Array(await preview.arrayBuffer()));
}

console.log(JSON.stringify({
  status: "ok",
  sheetNames,
  evidenceRows: evidenceRows.length,
  interfaceEvidenceRows: evidenceInterface.length,
  taskEvidenceRows: evidenceTasks.length,
  formulaErrors: formulaErrors.length,
  unchangedSheets: ["Code Description", "Old"],
  renders: renders.map((r) => r[2]),
}, null, 2));
