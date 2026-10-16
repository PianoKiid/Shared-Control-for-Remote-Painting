import { projectPath } from "../project_paths.mjs";
import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = projectPath("data/spreadsheets/source_snapshots/input_backup_before_sub12-14.xlsx");
const outputPath = projectPath("results/spreadsheets/인터뷰 정리_0728 - 복사본.xlsx");

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const counting = workbook.worksheets.getItem("Code Counting");
const quotation = workbook.worksheets.getItem("Code Quotation");
const remapParticipantIds = (value) => String(value)
  .replace(/\bS12\b/g, "S08")
  .replace(/\bS13\b/g, "S09")
  .replace(/\bS14\b/g, "S10");

const counts = [
  [
    "Total Count : 4\nPositive : S02, S13\nNegative : S07, S12",
    "Total Count : 5\nPositive : S13\nNegative : S03, S05, S06, S07",
    "Total Count : 6\nPositive : S03, S06, S07, S13\nNegative : S04, S12",
    "Total Count : 4\nPositive : S06\nNegative : S01, S05, S07",
  ],
  [
    "Total Count : 6\nPositive : S02, S04\nNegative : S01, S12, S13, S14",
    "Total Count : 4\nPositive : -\nNegative : S01, S06, S07, S14",
    "Total Count : 5\nPositive : S02, S13\nNegative : S06, S07, S14",
    "Total Count : 3\nPositive : S13\nNegative : S01, S07",
  ],
  [
    "Total Count : 2\nPositive : -\nNegative : S03, S04",
    "Total Count : 2\nPositive : -\nNegative : S03, S04",
    "Total Count : 2\nPositive : -\nNegative : S04, S05",
    "Total Count : 1\nPositive : -\nNegative : S04",
  ],
  [
    "Total Count : 3\nPositive : S02, S06\nNegative : S12",
    "Total Count : 3\nPositive : S02, S12\nNegative : S13",
    "Total Count : 8\nPositive : S02, S03\nNegative : S01, S04, S05, S06, S07, S12",
    "Total Count : 6\nPositive : S13, S14\nNegative : S03, S04, S05, S07",
  ],
  [
    "Total Count : 7\nPositive : S02, S04, S12\nNegative : S03, S05, S06, S07",
    "Total Count : 3\nPositive : S13\nNegative : S03, S07",
    "Total Count : 7\nPositive : -\nNegative : S02, S04, S05, S07, S12, S13, S14",
    "Total Count : 5\nPositive : S14\nNegative : S01, S04, S05, S12",
  ],
  [
    "Total Count : 3\nPositive : S12, S13, S14\nNegative : -",
    "Total Count : 4\nPositive : S02, S07\nNegative : S01, S03",
    "Total Count : 5\nPositive : -\nNegative : S01, S03, S07, S12, S14",
    "Total Count : 6\nPositive : S14\nNegative : S01, S02, S06, S07, S12",
  ],
  [
    "Total Count : 0",
    "Total Count : 8\nPositive : S02, S04, S12, S13\nNegative : S01, S05, S06, S13, S14",
    "Total Count : 0",
    "Total Count : 6\nPositive : S01, S03, S13, S14\nNegative : S04, S06",
  ],
  [
    "Total Count : 2\nPositive : -\nNegative : S06, S14",
    "Total Count : 1\nPositive : -\nNegative : S14",
    "Total Count : 5\nPositive : S01, S02, S06, S07\nNegative : S14",
    "Total Count : 5\nPositive : S01, S02, S12, S13, S14\nNegative : -",
  ],
  [
    "Total Count : 10\nPositive : S02, S04, S06, S12\nNegative : S01, S03, S05, S07, S13, S14",
    "Total Count : 8\nPositive : -\nNegative : S01~S07, S14",
    "Total Count : 10\nPositive : S06, S13, S14\nNegative : S01, S02, S03, S04, S05, S07, S12",
    "Total Count : 9\nPositive : S02, S12, S13\nNegative : S01, S03, S04, S05, S06, S07",
  ],
];
counting.getRange("D2:G10").values = counts.map((row) => row.map(remapParticipantIds));

const taskParticipants = [
  "S01, S03, S07, S12, S14",
  "S01, S07, S14",
  "S03, S05, S07, S12, S13, S14",
  "S03, S05, S07, S14",
  "S03, S05, S07, S12, S13, S14",
  "S01, S02, S04, S07, S13",
  "S02, S03, S04, S06, S07, S13, S14",
  "S01, S04, S07, S12, S13, S14",
  "S02, S12, S13, S14",
];
counting.getRange("D13:D21").values = taskParticipants.map((v) => [remapParticipantIds(v)]);

const quoteAdds = {
  D2: ["(S12) 모니터 화면에서 작업 영역이 작게 보여 가장자리의 미도장 부분을 확인하지 못했다.", "(S13) 칠해진 영역은 어느 정도 확인할 수 있었다."],
  E2: ["(S13) 경계면을 잡는 조작은 지연 없이 직관적으로 느껴졌다."],
  F2: ["(S12) 헤드셋에서 시선 방향이 바뀌어 경계를 맞추기 어려웠다.", "(S13) VR에서는 칠해진 부분과 덜 칠해진 부분의 대비가 더 분명하게 느껴졌다."],
  D3: ["(S12) 페인트 뭉침, 줄, 흐름과 같은 세부 결함이 화면에서 보이지 않았다.", "(S14) 모니터에서는 도막 두께 차이와 흐름 자국을 확인할 수 없었다."],
  E3: ["(S14) 롤러에 남은 페인트 양이 보이지 않아 도포 상태를 조절하기 어려웠다."],
  F3: ["(S13) VR에서 도포 영역의 대비가 더 명확하게 느껴졌다.", "(S14) 직접 눈으로 보는 것보다 세부 정보가 크게 줄어들었다."],
  G3: ["(S13) 가까이 이동하고 측면에서 보면서 덜 발린 부분과 도막 두께를 확인할 수 있었다."],
  D5: ["(S12) 전체 화면과 함께 결함을 부분 확대해 확인할 수 있는 기능이 필요했다."],
  E5: ["(S12) 3차원 정보와 확대 기능은 최종 완성도 점검에 도움이 될 것으로 보았다.", "(S13) 점군이 깨져 시점을 고정한 채 작업해야 했다."],
  F5: ["(S12) 머리 움직임에 따라 기준 시점이 흔들려 직선 작업이 어려웠다."],
  G5: ["(S13) 관찰 거리와 각도를 조정할 수 있어 작업이 수월했다.", "(S14) 작업 부위보다 낮은 시점으로 조정할 수 있어 편했다."],
  D6: ["(S12) 익숙한 평면 모니터에서는 조작 흐름을 유지하기 쉬웠다."],
  E6: ["(S13) 시점 조작이 지연 없이 반응하여 직관적으로 느껴졌다."],
  F6: ["(S12) 시선과 손 움직임이 함께 변해 작업선을 곧게 유지하기 어려웠다.", "(S13) 영상 끊김과 느린 반응이 작업을 방해했다.", "(S14) 로봇이 원하는 만큼 정밀하게 따라오지 않았다."],
  G6: ["(S12) 원하는 위치와 궤적으로 로봇을 움직이기 어려웠다.", "(S14) 3차원 시점을 조정할 수 있어 이전 조건보다 작업이 쉬웠다."],
  D7: ["(S12) 헤드셋보다 익숙한 모니터가 편했다.", "(S13) 화면을 통한 작업 자체에는 큰 부담을 느끼지 않았다.", "(S14) 장비를 착용하지 않아 모니터가 신체적으로 편했다."],
  F7: ["(S12) 네 조건 중 VR Stereo가 가장 어렵게 느껴졌다.", "(S14) 답답함과 어지러움이 있어 도수에 맞지 않는 안경을 쓴 느낌이었다."],
  G7: ["(S12) 로봇 조작에 익숙하지 않아 부담을 느꼈다.", "(S14) VR Stereo보다 난이도가 낮게 느껴졌다."],
  E8: ["(S12) 3차원 정보와 확대 기능의 활용 가치를 긍정적으로 평가했다.", "(S13) 시점 이동은 직관적이었지만 화면 깨짐 때문에 활용이 제한되었다.", "(S14) PCD 기능은 모니터에서 실효성이 낮았다."],
  G8: ["(S13) 가까이 이동하고 여러 각도에서 볼 수 있는 기능이 도움이 되었다.", "(S14) 시점을 작업 부위보다 낮게 조정할 수 있어 도움이 되었다."],
  D9: ["(S14) 모니터는 실제 표면을 보는 현장감이 부족했다."],
  E9: ["(S14) Monitor PCD는 종이를 펼쳐 놓고 색칠하는 것처럼 느껴졌다."],
  F9: ["(S14) VR이 새롭고 가능성은 있었지만 직접 보는 것보다 답답하고 어지러웠다."],
  G9: ["(S12) 3차원 공간을 입체적으로 보는 점을 긍정적으로 평가했다.", "(S13) 실제 공간을 보는 것처럼 느껴져 더 직관적이었다.", "(S14) 3차원 공간의 현장감과 몰입감이 높았다."],
  D10: ["(S12) 이전 조건보다 전체 면의 균일성이 좋아졌다고 평가했다.", "(S13) 초벌에는 가능하지만 최종 도장 품질에는 부족하다고 보았다.", "(S14) 결함이 보이지 않아 최종 마감 작업성이 떨어진다고 평가했다."],
  E10: ["(S14) 롤러의 페인트 양을 보지 못해 도포 품질을 조절하기 어려웠다."],
  F10: ["(S12) 네 조건 중 작업하기 가장 어렵게 느껴졌다.", "(S13) 지금까지의 조건 중 작업 결과가 가장 좋았다고 평가했다.", "(S14) 초벌 작업으로는 절반 이상 만족할 만하다고 평가했다."],
  G10: ["(S12) 최종 마감에는 부족하지만 초벌 작업에는 유용하다고 평가했다.", "(S13) 네 조건 중 작업 결과가 가장 좋았다고 평가했다."],
  D11: ["(S12) 결함과 미도장 영역을 확인하고 최종 완성도를 판단할 수 있어야 한다."],
  E11: ["(S14) 롤러에 남은 페인트 양과 도막 두께를 보면서 작업해야 한다."],
  D12: ["(S14) 페인트가 건조되기 전에 흐름과 두께 차이를 펴서 보정해야 한다."],
  E13: ["(S14) 페인트가 흐르기 전에 다시 위로 끌어올려 펴 바를 수 있어야 한다."],
  G13: ["(S12) 처음에는 약하게 바르고 이후 다시 펴는 과정이 필요하다.", "(S13) 롤러를 수직으로 대지 않고 약간 기울여 부드럽게 움직여야 한다."],
  E14: ["(S14) 롤러에 묻은 페인트 양을 알아야 한 번에 칠할 범위를 판단할 수 있다."],
  E15: ["(S14) 벽과 롤러 사이의 거리와 압력을 조절해야 도막 두께와 페인트 양을 관리할 수 있다."],
  G15: ["(S12) 롤러 털이 닿은 상태와 중심부까지 강하게 눌린 상태를 구분해야 한다.", "(S13) 벽에 가하는 압력과 롤러 각도를 조절하는 것이 중요하다."],
  E16: ["(S13) 경계 안을 세밀하게 채우는 데 가장 신경을 썼다."],
  E17: ["(S13) 여러 번 칠할 수 있으므로 우선 경계를 정확히 잡는 것이 중요하다."],
  F17: ["(S14) 테두리를 넘지 않으면서 경계까지 정확한 두께로 칠하는 데 신경을 썼다."],
  D18: ["(S14) 실제 표면과 같은 수준으로 줄무늬와 흐름이 보여야 한다."],
  E18: ["(S12) 확대하여 세부 결함과 최종 완성도를 확인할 수 있어야 한다.", "(S13) 넓은 현장에서도 시점을 옮길 때 화면이 깨지지 않아야 한다."],
  E19: ["(S14) 벽과의 거리와 압력을 섬세하게 조절할 수 있어야 한다."],
  G19: ["(S12) 진하게 누르는 상태와 연하게 누르는 상태를 구분해 조절할 수 있어야 한다.", "(S13) 작업자가 원하는 만큼 벽 압력을 조절할 수 있어야 한다."],
};
for (const [address, additions] of Object.entries(quoteAdds)) {
  const cell = quotation.getRange(address);
  const current = cell.values?.[0]?.[0];
  const base = current && current !== "-" ? String(current).trim() : "";
  const mappedAdditions = additions.map(remapParticipantIds);
  cell.values = [[base ? `${base}\n${mappedAdditions.join("\n")}` : mappedAdditions.join("\n")]];
}

const evidence = [];
const addEvidence = (participant, interfaceName, codeGroup, code, valence, source, timestamp, passage, rationale) => {
  evidence.push([remapParticipantIds(participant), interfaceName, codeGroup, code, valence, source, timestamp, passage, rationale]);
};

// Interface-specific coding evidence.
addEvidence("S12", "Monitor Stereo", "Interface experience", "Paint Area Perception", "Negative", "12-MS.txt", "13:05–14:12", "모니터 화면에서 작업 영역이 작게 보여 가장자리의 미도장 부분을 확인하지 못했다.", "축소된 화면 때문에 경계와 미도장 영역을 완료 상태로 오인함.");
addEvidence("S12", "Monitor Stereo", "Interface experience", "Surface and Defect Visibility", "Negative", "12-MS.txt", "16:19–17:25", "페인트 뭉침, 줄, 흐름과 같은 세부 결함이 화면에서는 잘 보이지 않았다.", "도장면의 세부 결함을 시각적으로 확인하지 못함.");
addEvidence("S12", "Monitor Stereo", "Interface experience", "Viewpoint Adjustment", "Negative", "12-MS.txt", "18:09–18:23", "전체 화면과 함께 결함을 부분 확대해 확인할 수 있는 기능이 필요했다.", "현재 고정 축척만으로는 최종 검사가 어려워 확대 시점이 필요함.");
addEvidence("S12", "Monitor Stereo", "Interface experience", "Motion Precision & Stability", "Positive", "12-MS.txt", "14:31–14:53", "페인트가 흐르지 않도록 고르게 펴 바르는 조절이 이전보다 나아졌다.", "익숙한 고정 화면에서 조작 안정성이 향상되었다고 평가함.");
addEvidence("S12", "Monitor Stereo", "Interface experience", "Physical & Cognitive Workload", "Positive", "12-MS.txt", "09:20–10:09", "헤드셋보다 익숙한 평면 모니터를 보는 편이 편했다.", "착용 부담과 낯섦이 적어 상대적으로 편안하다고 평가함.");
addEvidence("S12", "Monitor Stereo", "Interface experience", "Perceived Paint Quality", "Positive", "12-MS.txt", "09:01–09:30", "이전 조건보다 전체 면의 균일성이 20~30% 좋아졌다고 느꼈다.", "결과물의 균일성이 상대적으로 향상되었다고 평가함.");
addEvidence("S13", "Monitor Stereo", "Interface experience", "Paint Area Perception", "Positive", "13-MS.txt", "13:04–13:46", "화면에서 칠해진 영역을 어느 정도 확인할 수 있었다.", "거친 수준의 도포 영역 구분은 가능했다고 평가함.");
addEvidence("S13", "Monitor Stereo", "Interface experience", "Surface and Defect Visibility", "Negative", "13-MS.txt", "13:04–13:46", "칠해진 부분과 덜 칠해진 부분의 세세한 차이는 구분하기 어려웠다.", "세부 도포 상태의 시각적 판별이 부족함.");
addEvidence("S13", "Monitor Stereo", "Interface experience", "Physical & Cognitive Workload", "Positive", "13-MS.txt", "19:00–19:36", "화면을 통한 작업 자체에는 큰 거리감이나 답답함을 느끼지 않았다.", "평소 화면 사용에 익숙해 별도 부담이 적었다고 평가함.");
addEvidence("S13", "Monitor Stereo", "Interface experience", "Perceived Paint Quality", "Negative", "13-MS.txt", "13:04–13:46", "프라이머나 초벌에는 괜찮지만 최종 도장으로는 부족하다고 보았다.", "현재 결과가 최종 마감 품질에는 미달한다고 평가함.");
addEvidence("S14", "Monitor Stereo", "Interface experience", "Surface and Defect Visibility", "Negative", "14-MS.txt", "00:21–04:06", "모니터에서는 줄무늬, 흐름, 도막 두께 차이와 같은 결함이 보이지 않았다.", "직접 시야에서는 보이는 마감 결함을 화면에서 확인하지 못함.");
addEvidence("S14", "Monitor Stereo", "Interface experience", "Physical & Cognitive Workload", "Positive", "14-MS.txt", "04:09–04:41", "헤드셋을 착용하지 않아 모니터 방식이 신체적으로 편했다.", "착용 장비가 없어 작업 부담이 낮다고 평가함.");
addEvidence("S14", "Monitor Stereo", "Interface experience", "Perceived Presence & Immersion", "Negative", "14-MS.txt", "02:25–04:06", "모니터는 실제 표면을 보는 현장감이 부족했다.", "실제 표면과 동일한 느낌을 제공하지 못함.");
addEvidence("S14", "Monitor Stereo", "Interface experience", "Perceived Paint Quality", "Negative", "14-MS.txt", "03:05–04:06", "결함을 확인할 수 없어 최종 마감 작업성이 떨어진다고 평가했다.", "시각적 누락 때문에 결과물이 하자로 이어질 수 있다고 판단함.");

addEvidence("S12", "Monitor PCD", "Interface experience", "Viewpoint Adjustment", "Positive", "12-MP.txt", "07:26–08:39", "전체 작업 영역을 본 뒤 필요한 부분을 확대해 최종 완성도를 점검하는 방식이 적합하다고 보았다.", "전체 시점과 확대 검사를 결합하는 방식을 긍정적으로 평가함.");
addEvidence("S12", "Monitor PCD", "Interface experience", "Point Cloud View Navigation", "Positive", "12-MP.txt", "06:23–08:39", "3차원 정보와 확대 기능이 세부 결함과 완성도 점검에 도움이 될 것으로 보았다.", "PCD의 이동·확대 기능에 활용 가치가 있다고 평가함.");
addEvidence("S13", "Monitor PCD", "Interface experience", "Paint Area Perception", "Positive", "13-MP.txt", "00:37–01:11", "경계면을 잡는 조작은 지연 없이 직관적으로 느껴졌다.", "경계와 작업 위치를 보며 조작하기 충분했다고 평가함.");
addEvidence("S13", "Monitor PCD", "Interface experience", "Viewpoint Adjustment", "Negative", "13-MP.txt", "01:11–01:55", "시점을 크게 바꾸면 화면이 깨져 깨지지 않는 각도에 고정하고 작업했다.", "자유 시점 기능을 실제로 활용하지 못함.");
addEvidence("S13", "Monitor PCD", "Interface experience", "Motion Precision & Stability", "Positive", "13-MP.txt", "00:37–01:11", "화면이 지연 없이 반응해 조작이 직관적이고 작업하기 충분했다.", "입력과 화면 반응이 안정적이었다고 평가함.");
addEvidence("S13", "Monitor PCD", "Interface experience", "Point Cloud View Navigation", "Positive", "13-MP.txt", "00:37–01:11", "시점 조작이 지연 없이 반응해 긍정적으로 느껴졌다.", "PCD 시점 이동의 반응성을 긍정적으로 평가함.");
addEvidence("S13", "Monitor PCD", "Interface experience", "Point Cloud View Navigation", "Negative", "13-MP.txt", "01:11–01:55", "시점을 움직일 때 점군이 깨져 기능 활용이 제한되었다.", "점군 재구성 깨짐이 내비게이션의 부정적 요인임.");
addEvidence("S14", "Monitor PCD", "Interface experience", "Surface and Defect Visibility", "Negative", "14-MP.txt", "00:00–01:45", "롤러에 남은 페인트 양이 보이지 않아 도포 상태를 조절하기 어려웠다.", "페인트 잔량과 도포 상태가 시각적으로 드러나지 않음.");
addEvidence("S14", "Monitor PCD", "Interface experience", "Point Cloud View Navigation", "Negative", "14-MP.txt", "05:15–06:24", "PCD의 시점 기능은 모니터에서 실효성이 낮다고 보았다.", "같은 3차원 기능이 VR보다 직관적이지 않았음.");
addEvidence("S14", "Monitor PCD", "Interface experience", "Perceived Presence & Immersion", "Negative", "14-MP.txt", "05:15–06:19", "종이를 펼쳐 놓고 색칠하는 것처럼 느껴져 현장감이 부족했다.", "실제 작업 공간에 있는 느낌이 부족함.");
addEvidence("S14", "Monitor PCD", "Interface experience", "Perceived Paint Quality", "Negative", "14-MP.txt", "00:00–01:45", "페인트 양을 보지 못해 스트로크 길이와 재도포를 조절하지 못했다.", "시각정보 부족이 결과 품질 관리에 부정적으로 작용함.");

addEvidence("S12", "VR Stereo", "Interface experience", "Paint Area Perception", "Negative", "12-MP.txt", "01:10–02:22", "기준 시점이 움직여 직선 작업과 경계 맞추기가 어려웠다.", "헤드 움직임 때문에 경계와 작업선 인지가 불안정함.");
addEvidence("S12", "VR Stereo", "Interface experience", "Viewpoint Adjustment", "Negative", "12-MP.txt", "05:21–06:13", "머리 움직임에 따라 보이는 방향도 함께 달라져 기준 시점이 흔들렸다.", "시점이 의도치 않게 변해 작업에 방해가 됨.");
addEvidence("S12", "VR Stereo", "Interface experience", "Motion Precision & Stability", "Negative", "12-MP.txt", "01:10–02:22", "롤러를 일자로 내리려 해도 옆으로 벗어나 원하는 궤적을 유지하기 어려웠다.", "시점 변화와 손 움직임의 결합이 정밀 조작을 저해함.");
addEvidence("S12", "VR Stereo", "Interface experience", "Physical & Cognitive Workload", "Negative", "12-MP.txt", "06:09–06:23", "네 조건 중 마지막 VR 평면 영상이 가장 어렵게 느껴졌다.", "헤드셋과 평면 영상의 조합이 높은 부담을 유발함.");
addEvidence("S12", "VR Stereo", "Interface experience", "Perceived Paint Quality", "Negative", "12-MP.txt", "04:33–05:21", "마지막 조건은 작업 결과가 가장 부족했다고 평가했다.", "결과물의 균일도와 경계 수행이 가장 낮았다고 판단함.");
addEvidence("S13", "VR Stereo", "Interface experience", "Paint Area Perception", "Positive", "13-VS.txt", "00:05–01:57", "VR에서는 칠해진 부분과 덜 칠해진 부분의 차이가 더 분명하게 느껴졌다.", "도포 영역의 대비가 더 명확했다고 평가함.");
addEvidence("S13", "VR Stereo", "Interface experience", "Surface and Defect Visibility", "Positive", "13-VS.txt", "00:05–01:57", "도포량이 부족한 부분을 더 잘 인식할 수 있었다.", "표면의 도포 차이를 시각적으로 확인함.");
addEvidence("S13", "VR Stereo", "Interface experience", "Motion Precision & Stability", "Negative", "13-VS.txt", "02:03–02:44", "영상이 간헐적으로 끊기고 움직임에 대한 반응이 느리게 느껴졌다.", "영상 지연과 끊김이 안정적인 조작을 방해함.");
addEvidence("S13", "VR Stereo", "Interface experience", "Perceived Paint Quality", "Positive", "13-VS.txt", "00:05–00:36", "지금까지 수행한 조건 중 작업 결과가 가장 좋았다고 평가했다.", "결과물 품질을 상대적으로 가장 높게 평가함.");
addEvidence("S14", "VR Stereo", "Interface experience", "Surface and Defect Visibility", "Negative", "14-VS.txt", "03:50–04:37", "직접 눈으로 보는 것보다 세부 정보가 크게 줄어든다고 느꼈다.", "매개된 영상에서 표면 세부정보가 손실됨.");
addEvidence("S14", "VR Stereo", "Interface experience", "Motion Precision & Stability", "Negative", "14-VS.txt", "08:11–09:12", "원하는 만큼 로봇이 따라오지 않아 정밀 제어가 어려웠다.", "원격 입력과 로봇 동작 사이의 정밀성이 부족함.");
addEvidence("S14", "VR Stereo", "Interface experience", "Physical & Cognitive Workload", "Negative", "14-VS.txt", "05:50–06:59", "가상 공간이 답답하고 어지러워 도수에 맞지 않는 안경을 쓴 느낌이었다.", "헤드셋 착용과 가상영상이 신체·인지 부담을 유발함.");
addEvidence("S14", "VR Stereo", "Interface experience", "Perceived Presence & Immersion", "Negative", "14-VS.txt", "03:50–04:37", "직접 보는 것보다 답답하고 간접적으로 느껴졌다.", "직접 현장 시야에 비해 현장감이 낮다고 평가함.");
addEvidence("S14", "VR Stereo", "Interface experience", "Perceived Paint Quality", "Positive", "14-VS.txt", "00:19–00:46", "최종 마감은 아니지만 한 번 칠하는 초벌로는 절반 이상 괜찮다고 평가했다.", "초벌 결과물의 품질을 제한적으로 긍정 평가함.");

addEvidence("S12", "VR PCD", "Interface experience", "Motion Precision & Stability", "Negative", "12-VP.txt", "12:58–14:13", "로봇 조작에 익숙하지 않아 원하는 위치와 궤적으로 움직이기 어려웠다.", "입력 숙련 부족과 제한된 작업 범위가 정밀 조작을 저해함.");
addEvidence("S12", "VR PCD", "Interface experience", "Physical & Cognitive Workload", "Negative", "12-VP.txt", "12:58–14:13", "기계 작동 방법에 익숙하지 않은 점이 가장 어려웠다.", "인터페이스 및 조작 학습 부담이 컸음.");
addEvidence("S12", "VR PCD", "Interface experience", "Perceived Presence & Immersion", "Positive", "12-VP.txt", "11:43–12:39", "3차원 공간을 입체적으로 볼 수 있다는 점을 긍정적으로 평가했다.", "3차원 VR 표현이 현장 이해와 일체감 형성에 도움이 된다고 봄.");
addEvidence("S12", "VR PCD", "Interface experience", "Perceived Paint Quality", "Positive", "12-VP.txt", "09:55–11:05", "최종 마감에는 부족하지만 초벌 작업에는 충분히 유용한 수준이라고 평가했다.", "초벌 품질과 작업량 절감 측면에서 긍정적으로 평가함.");
addEvidence("S13", "VR PCD", "Interface experience", "Surface and Defect Visibility", "Positive", "13-VP.txt", "00:47–01:35", "가까이 이동하고 측면에서 보면서 덜 발린 부분과 도막 두께를 확인할 수 있었다.", "가까운 거리와 측면 시점이 표면 상태 판별을 지원함.");
addEvidence("S13", "VR PCD", "Interface experience", "Viewpoint Adjustment", "Positive", "13-VP.txt", "00:47–01:35", "관찰 거리와 각도를 조정할 수 있어 작업이 수월했다.", "시점 이동이 국소 검사와 작업 위치 판단에 도움을 줌.");
addEvidence("S13", "VR PCD", "Interface experience", "Point Cloud View Navigation", "Positive", "13-VP.txt", "00:47–02:17", "가까이 이동하고 여러 각도에서 볼 수 있는 기능이 도움이 되었다.", "PCD의 자유 시점 기능을 실제 작업에 활용함.");
addEvidence("S13", "VR PCD", "Interface experience", "Perceived Presence & Immersion", "Positive", "13-VP.txt", "01:44–02:17", "모니터보다 실제 공간을 보는 것처럼 느껴져 더 직관적이었다.", "VR과 3차원 공간의 결합에서 높은 현장감을 느낌.");
addEvidence("S13", "VR PCD", "Interface experience", "Perceived Paint Quality", "Positive", "13-VP.txt", "00:01–00:47", "네 조건 중 작업 결과가 가장 좋았다고 평가했다.", "도포량과 균일성을 가장 잘 관리한 결과로 판단함.");
addEvidence("S14", "VR PCD", "Interface experience", "Viewpoint Adjustment", "Positive", "14-VP.txt", "00:23–01:17", "작업 부위보다 낮은 위치로 시점을 조정할 수 있어 편했다.", "실제 도장 자세에 맞는 시선 방향을 만들 수 있었음.");
addEvidence("S14", "VR PCD", "Interface experience", "Motion Precision & Stability", "Positive", "14-VP.txt", "01:17–02:54", "시각이 편해져 이전 2차원 VR 조건보다 작업이 덜 어려웠다.", "조정 가능한 3차원 시점이 조작 난이도를 낮춤.");
addEvidence("S14", "VR PCD", "Interface experience", "Physical & Cognitive Workload", "Positive", "14-VP.txt", "02:22–02:54", "VR Stereo보다 작업이 덜 어렵게 느껴졌다.", "3차원 표현이 VR 작업 부담을 상대적으로 낮춤.");
addEvidence("S14", "VR PCD", "Interface experience", "Point Cloud View Navigation", "Positive", "14-VP.txt", "00:23–01:17", "시점을 이동하며 원하는 방향에서 볼 수 있어 작업이 수월했다.", "PCD 시점 이동을 적극적으로 활용함.");
addEvidence("S14", "VR PCD", "Interface experience", "Perceived Presence & Immersion", "Positive", "14-VP.txt", "02:32–02:56", "3차원 공간으로 보니 현장감과 몰입감이 더 높았다.", "VR Stereo보다 높은 현장감을 느낌.");

// Task-focused coding evidence. These codes are counted once per participant across all conditions.
const taskRows = [
  ["S12", "All conditions", "Task need / strategy", "Painting State Monitoring", "Not applicable", "12-MS.txt", "16:19–18:23", "결함과 미도장 영역을 확인하고 최종 완성도를 판단할 수 있어야 한다.", "작업 중 도포 상태와 완성도 확인 요구."],
  ["S12", "All conditions", "Task need / strategy", "Immediate Defect Correction", "Not applicable", "12-VP.txt", "02:34–04:15", "페인트가 흐르기 전에 다시 끌어올려 펴 바르는 조절이 필요하다.", "결함 발생 직후 보정하는 작업 관행."],
  ["S12", "All conditions", "Task need / strategy", "Painting Motion & Pass Strategy", "Not applicable", "12-VP.txt", "15:19–17:04", "처음에는 약하게 바르고 이후 다시 펴는 과정이 필요하다.", "도포와 마감 단계에 따른 반복 패스 전략."],
  ["S12", "All conditions", "Task need / strategy", "Paint Supply and Material Condition Management", "Not applicable", "12-MS.txt", "09:01–09:30", "초벌에서는 얇더라도 빠진 곳 없이 균일하게 묻히는 것이 중요하다.", "도료 분포와 초벌 상태 관리."],
  ["S12", "All conditions", "Task need / strategy", "Roller Contact and Orientation Control", "Not applicable", "12-VP.txt", "14:17–16:39", "롤러 털이 닿은 상태와 중심부까지 강하게 눌린 상태를 구분해야 한다.", "롤러 접촉 정도와 압력 조절 요구."],
  ["S12", "All conditions", "Task need / strategy", "Precise Execution", "Not applicable", "12-MP.txt", "01:10–02:22", "롤러를 일자로 내리며 원하는 궤적을 유지해야 한다.", "정확한 경로 수행 전략."],
  ["S12", "All conditions", "Task need / strategy", "Work Boundary Adherence", "Not applicable", "12-MP.txt", "01:39–02:22", "작업선이 옆으로 벗어나지 않도록 경계를 지켜야 한다.", "지정 영역의 경계 준수 전략."],
  ["S12", "All conditions", "Task need / strategy", "Enhanced Visual Inspection Support", "Not applicable", "12-MP.txt", "08:19–08:39", "확대하여 세부 결함과 최종 완성도를 확인할 수 있어야 한다.", "확대·검사 기능 요구."],
  ["S12", "All conditions", "Task need / strategy", "Fine Roller Contact Adjustment", "Not applicable", "12-VP.txt", "16:09–17:37", "진하게 누르는 상태와 연하게 누르는 상태를 구분해 조절할 수 있어야 한다.", "미세 접촉 깊이와 압력 조정 요구."],
  ["S13", "All conditions", "Task need / strategy", "Painting State Monitoring", "Not applicable", "13-VP.txt", "00:47–01:35", "덜 발린 부분과 페인트 양, 도막 두께를 확인할 수 있어야 한다.", "도포 상태 모니터링 요구."],
  ["S13", "All conditions", "Task need / strategy", "Painting Motion & Pass Strategy", "Not applicable", "13-VP.txt", "06:32–08:10", "롤러를 수직으로 대지 않고 약간 기울여 부드럽게 움직여야 한다.", "롤러 각도에 따른 패스 전략."],
  ["S13", "All conditions", "Task need / strategy", "Roller Contact and Orientation Control", "Not applicable", "13-VP.txt", "05:14–07:45", "벽에 가하는 압력과 롤러 각도를 조절하는 것이 중요하다.", "접촉 압력과 방향 제어 요구."],
  ["S13", "All conditions", "Task need / strategy", "Precise Execution", "Not applicable", "13-MP.txt", "02:06–04:02", "경계 안을 세밀하게 채우는 데 가장 신경을 썼다.", "목표 영역을 정확히 따라가는 전략."],
  ["S13", "All conditions", "Task need / strategy", "Work Boundary Adherence", "Not applicable", "13-MP.txt", "02:06–02:30", "여러 번 칠할 수 있으므로 우선 경계를 정확히 잡는 것이 중요하다.", "작업 경계 준수의 우선순위."],
  ["S13", "All conditions", "Task need / strategy", "Enhanced Visual Inspection Support", "Not applicable", "13-MP.txt", "04:47–05:09", "넓은 현장에서도 시점을 옮길 때 화면이 깨지지 않아야 한다.", "안정적인 확대·시점 검사 기능 요구."],
  ["S13", "All conditions", "Task need / strategy", "Fine Roller Contact Adjustment", "Not applicable", "13-VP.txt", "05:14–06:05", "작업자가 원하는 만큼 벽 압력을 조절할 수 있어야 한다.", "접촉 압력의 미세 조절 요구."],
  ["S14", "All conditions", "Task need / strategy", "Painting State Monitoring", "Not applicable", "14-MP.txt", "00:00–01:45", "롤러에 남은 페인트 양과 도막 두께를 보면서 작업해야 한다.", "도포량과 재료 상태 모니터링 요구."],
  ["S14", "All conditions", "Task need / strategy", "Immediate Defect Correction", "Not applicable", "14-MS.txt", "00:55–02:09", "페인트가 건조되기 전에 흐름과 두께 차이를 펴서 보정해야 한다.", "결함을 즉시 수정하는 작업 요구."],
  ["S14", "All conditions", "Task need / strategy", "Painting Motion & Pass Strategy", "Not applicable", "14-MP.txt", "00:30–01:19", "페인트가 흐르기 전에 다시 위로 끌어올려 펴 바를 수 있어야 한다.", "도료 상태에 맞춘 반복 패스 전략."],
  ["S14", "All conditions", "Task need / strategy", "Paint Supply and Material Condition Management", "Not applicable", "14-MP.txt", "00:30–01:45", "롤러에 묻은 페인트 양을 알아야 한 번에 칠할 범위를 판단할 수 있다.", "롤러의 도료 잔량 관리 요구."],
  ["S14", "All conditions", "Task need / strategy", "Roller Contact and Orientation Control", "Not applicable", "14-MP.txt", "11:10–11:31", "벽과 롤러 사이의 거리와 압력을 조절해야 도막 두께와 페인트 양을 관리할 수 있다.", "접촉 거리와 압력 제어 요구."],
  ["S14", "All conditions", "Task need / strategy", "Precise Execution", "Not applicable", "14-MP.txt", "11:10–11:31", "섬세한 로봇 움직임으로 도막 두께를 조절할 수 있어야 한다.", "정밀한 작업 수행 요구."],
  ["S14", "All conditions", "Task need / strategy", "Work Boundary Adherence", "Not applicable", "14-VS.txt", "07:13–08:08", "테두리를 넘지 않으면서 경계까지 정확한 두께로 칠하는 데 신경을 썼다.", "지정 경계 준수 전략."],
  ["S14", "All conditions", "Task need / strategy", "Enhanced Visual Inspection Support", "Not applicable", "14-MS.txt", "03:05–04:41", "실제 표면과 같은 수준으로 줄무늬와 흐름이 보여야 한다.", "고해상도 표면 검사 지원 요구."],
  ["S14", "All conditions", "Task need / strategy", "Fine Roller Contact Adjustment", "Not applicable", "14-MP.txt", "11:10–11:31", "벽과의 거리와 압력을 섬세하게 조절할 수 있어야 한다.", "미세 접촉 조정 기능 요구."],
];
const excludedTaskCodings = new Set([
  "S12|Immediate Defect Correction",
  "S12|Paint Supply and Material Condition Management",
  "S12|Precise Execution",
  "S12|Work Boundary Adherence",
  "S13|Painting State Monitoring",
  "S14|Precise Execution",
]);
const strictTaskRows = taskRows
  .filter((row) => !excludedTaskCodings.has(`${row[0]}|${row[3]}`))
  .map((row) => [remapParticipantIds(row[0]), ...row.slice(1)]);
evidence.push(...strictTaskRows);

const evidenceSheet = workbook.worksheets.add("Coding Evidence");
evidenceSheet.showGridLines = false;
evidenceSheet.freezePanes.freezeRows(1);
const headers = [["Participant ID", "Interface", "Code group", "Code", "Valence", "Source transcript", "Timestamp", "Counted passage", "Coding rationale"]];
evidenceSheet.getRange("A1:I1").values = headers;
evidenceSheet.getRange("A2").write(evidence);
const lastRow = evidence.length + 1;
evidenceSheet.getRange(`A1:I${lastRow}`).format.font = { name: "맑은 고딕", size: 10 };
evidenceSheet.getRange("A1:I1").format = {
  font: { name: "맑은 고딕", size: 11, bold: true },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "doubleBottom", style: "thin", color: "#808080" },
};
evidenceSheet.getRange(`A2:G${lastRow}`).format.verticalAlignment = "top";
evidenceSheet.getRange(`A2:G${lastRow}`).format.horizontalAlignment = "center";
evidenceSheet.getRange(`H2:I${lastRow}`).format.verticalAlignment = "top";
evidenceSheet.getRange(`H2:I${lastRow}`).format.horizontalAlignment = "left";
evidenceSheet.getRange(`A1:I${lastRow}`).format.wrapText = true;
evidenceSheet.getRange("A:A").format.columnWidth = 12;
evidenceSheet.getRange("B:B").format.columnWidth = 18;
evidenceSheet.getRange("C:C").format.columnWidth = 22;
evidenceSheet.getRange("D:D").format.columnWidth = 34;
evidenceSheet.getRange("E:E").format.columnWidth = 14;
evidenceSheet.getRange("F:F").format.columnWidth = 18;
evidenceSheet.getRange("G:G").format.columnWidth = 16;
evidenceSheet.getRange("H:H").format.columnWidth = 70;
evidenceSheet.getRange("I:I").format.columnWidth = 52;
evidenceSheet.getRange(`A2:I${lastRow}`).format.borders = { preset: "inside", style: "thin", color: "#E0E0E0" };
evidenceSheet.getRange(`H2:I${lastRow}`).format.autofitRows();

counting.getRange("D2:G10").format.autofitRows();
counting.getRange("D13:D21").format.autofitRows();
quotation.getRange("D2:G10").format.autofitRows();

workbook.recalculate();
await fs.mkdir(projectPath("results/spreadsheets"), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({ outputPath, evidenceRows: evidence.length, lastRow }, null, 2));
