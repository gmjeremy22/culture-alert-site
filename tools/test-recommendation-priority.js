const fs = require("fs");
const vm = require("vm");

const htmlPath =
  process.argv[2] ||
  "automation/culture-alert/outputs/keyword-recommendation-report.html";

function fail(message) {
  throw new Error(`recommendation priority audit failed: ${message}`);
}

const html = fs.readFileSync(htmlPath, "utf8");
const scriptStart = html.lastIndexOf("<script>");
const scriptEnd = html.lastIndexOf("</script>");
if (scriptStart < 0 || scriptEnd <= scriptStart) {
  fail("main script was not found");
}

const script = html.slice(scriptStart + "<script>".length, scriptEnd);
const itemsMatch = script.match(
  /const items = ([\s\S]*?);\r?\n\s*const institutions/
);
if (!itemsMatch) {
  fail("recommendation item data was not found");
}
const items = JSON.parse(itemsMatch[1]);
const rankingStart = script.indexOf("function urgencyScore");
const rankingEnd = script.indexOf("function scoreDiscovery", rankingStart);
if (rankingStart < 0 || rankingEnd <= rankingStart) {
  fail("recommendation ranking implementation was not found");
}

const source = `
  function numeric(value) {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  const selectedKeywords = new Set();
  const recommendationState = { priority: "recommended" };
  function selectedKeywordCount() { return 0; }
  ${script.slice(rankingStart, rankingEnd)}
  globalThis.rankingApi = {
    recommendationState,
    institutionPriorityTier,
    scoreRecommendation,
    compareRecommendationEntries
  };
`;

const context = {};
vm.runInNewContext(source, context, { timeout: 10000 });
const api = context.rankingApi;

function entry(item, index) {
  return {
    item,
    index,
    score: api.scoreRecommendation(item, index),
  };
}

const majorLongRunning = entry(
  {
    title: "주요 기관 장기 전시",
    institutionScaleScore: 78,
    isMajorInstitution: true,
    remainingDays: 120,
    startsInDays: 0,
    eventNature: "long_term",
    score: 1,
    imageUrl: "",
    occurrences: [],
  },
  0
);
const minorClosingSoon = entry(
  {
    title: "소규모 기관 내일 종료 전시",
    institutionScaleScore: 42,
    isMajorInstitution: false,
    remainingDays: 1,
    startsInDays: 0,
    eventNature: "limited",
    score: 8,
    imageUrl: "fixture.jpg",
    occurrences: [],
  },
  1
);

api.recommendationState.priority = "recommended";
if (
  [minorClosingSoon, majorLongRunning].sort(
    api.compareRecommendationEntries
  )[0] !== majorLongRunning
) {
  fail("a closing-soon minor institution outranked a major institution");
}

api.recommendationState.priority = "deadline";
if (
  [minorClosingSoon, majorLongRunning].sort(
    api.compareRecommendationEntries
  )[0] !== majorLongRunning
) {
  fail("deadline mode overrode the major-institution tier");
}

const majorLater = entry(
  {
    ...majorLongRunning.item,
    title: "주요 기관 다음 달 종료 전시",
    remainingDays: 28,
  },
  2
);
const majorSooner = entry(
  {
    ...majorLongRunning.item,
    title: "주요 기관 이번 주 종료 전시",
    remainingDays: 3,
  },
  3
);
api.recommendationState.priority = "deadline";
if (
  [majorLater, majorSooner].sort(api.compareRecommendationEntries)[0] !==
  majorSooner
) {
  fail("deadline mode did not order exhibitions inside the same tier");
}

const curationStart = script.indexOf("function renderCuration");
const majorSelection = script.indexOf("const majorCandidates", curationStart);
const deadlineSelection = script.indexOf("const endingSoon", curationStart);
if (
  curationStart < 0 ||
  majorSelection < curationStart ||
  deadlineSelection < majorSelection
) {
  fail("the main institution shelf is not populated before the deadline panel");
}

api.recommendationState.priority = "recommended";
const liveSeoulExhibitions = items
  .filter(
    (item) =>
      item.type === "전시" &&
      item.region === "서울" &&
      !item.isPermanent &&
      item.recommendationEligible !== false &&
      (item.remainingDays === null ||
        item.remainingDays === undefined ||
        Number(item.remainingDays) >= 0)
  )
  .map((item, index) => entry(item, index))
  .sort(api.compareRecommendationEntries);
const liveMajorCount = liveSeoulExhibitions.filter(
  (candidate) => api.institutionPriorityTier(candidate.item) >= 2
).length;
const priorityWindow = Math.min(8, liveMajorCount);
if (
  liveSeoulExhibitions
    .slice(0, priorityWindow)
    .some((candidate) => api.institutionPriorityTier(candidate.item) < 2)
) {
  fail("the live Seoul recommendation window contains a lower-tier institution");
}

console.log(
  `recommendation priority audit passed: ${priorityWindow} leading Seoul cards are major-institution tier`
);
