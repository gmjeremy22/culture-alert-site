const fs = require("fs");

const htmlPath =
  process.argv[2] ||
  "automation/culture-alert/outputs/keyword-recommendation-report.html";

function fail(message) {
  throw new Error(`schedule separation audit failed: ${message}`);
}

function sameIndexes(actual, expected) {
  const left = [...new Set(actual)].sort((a, b) => a - b);
  const right = [...new Set(expected)].sort((a, b) => a - b);
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

const html = fs.readFileSync(htmlPath, "utf8");
const itemsMatch = html.match(
  /const items = ([\s\S]*?);\r?\n\s*const institutions/
);
if (!itemsMatch) fail("item data was not found");
const items = JSON.parse(itemsMatch[1]);

function isUpcoming(item) {
  if (typeof item.startsInDays === "number") return item.startsInDays > 0;
  return String(item.status || "").includes("예정");
}

const cardMatches = [...html.matchAll(
  /<article class="([^"]+)"[^>]*data-feature-index="(\d+)"/g
)];
const indexesByClass = (className) =>
  cardMatches
    .filter((match) => match[1].split(/\s+/).includes(className))
    .map((match) => Number(match[2]));

const currentExhibitions = items
  .map((item, index) => ({ item, index }))
  .filter(({ item }) => !item.isPermanent && item.type === "전시" && !isUpcoming(item))
  .map(({ index }) => index);
const currentPrograms = items
  .map((item, index) => ({ item, index }))
  .filter(
    ({ item }) =>
      !item.isPermanent &&
      ["강연", "교육", "행사"].includes(item.type) &&
      !isUpcoming(item)
  )
  .map(({ index }) => index);
const upcomingSchedules = items
  .map((item, index) => ({ item, index }))
  .filter(({ item }) => !item.isPermanent && isUpcoming(item))
  .map(({ index }) => index);
const permanentExhibitions = items
  .map((item, index) => ({ item, index }))
  .filter(({ item }) => item.isPermanent)
  .map(({ index }) => index);

for (const item of items) {
  const itemUpcoming = isUpcoming(item);
  const mixedCompanion = (item.companionEvents || []).find(
    (companion) => isUpcoming(companion) !== itemUpcoming
  );
  if (mixedCompanion) {
    fail(`same-venue curation mixes current and upcoming schedules for item ${item.id}`);
  }
}

if (!sameIndexes(indexesByClass("feature-card"), currentExhibitions)) {
  fail("the recommendation card pool contains missing or upcoming exhibitions");
}
if (!sameIndexes(indexesByClass("program-card"), currentPrograms)) {
  fail("the program tab contains missing or upcoming programs");
}
if (!sameIndexes(indexesByClass("upcoming-card"), upcomingSchedules)) {
  fail("the upcoming tab does not exactly match future-start schedules");
}
const renderedUpcomingIndexes = indexesByClass("upcoming-card");
const renderedStartOrder = renderedUpcomingIndexes.map((index) =>
  typeof items[index].startsInDays === "number" ? items[index].startsInDays : 99999
);
if (renderedStartOrder.some((value, index) => index > 0 && value < renderedStartOrder[index - 1])) {
  fail("the upcoming tab is not ordered by the nearest start date");
}
const upcomingStateCount = (html.match(/class="upcoming-state"/g) || []).length;
if (upcomingStateCount !== upcomingSchedules.length) {
  fail("an upcoming card is missing its explicit start-state label");
}
if (
  !sameIndexes(
    indexesByClass("list-card"),
    [...currentExhibitions, ...permanentExhibitions]
  )
) {
  fail("the current/permanent lists contain an unexpected schedule");
}
if (
  !html.includes('data-view="upcoming"') ||
  !html.includes('id="upcomingView"') ||
  !html.includes('id="upcomingGrid"') ||
  !html.includes('upcomingView.hidden = view !== "upcoming"')
) {
  fail("the independent upcoming view is missing or not connected");
}

console.log(
  `schedule separation audit passed: current exhibitions=${currentExhibitions.length}, ` +
    `current programs=${currentPrograms.length}, upcoming=${upcomingSchedules.length}`
);
