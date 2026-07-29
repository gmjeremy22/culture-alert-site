const fs = require("fs");
const vm = require("vm");

const htmlPath =
  process.argv[2] ||
  "automation/culture-alert/outputs/keyword-recommendation-report.html";

function fail(message) {
  console.error(`search audit failed: ${message}`);
  process.exitCode = 1;
}

function extractSearchApi(html) {
  const scriptStart = html.lastIndexOf("<script>");
  const scriptEnd = html.lastIndexOf("</script>");
  if (scriptStart < 0 || scriptEnd <= scriptStart) {
    throw new Error("main script was not found");
  }
  const script = html.slice(scriptStart + "<script>".length, scriptEnd);
  const itemsMatch = script.match(
    /const items = ([\s\S]*?);\r?\n\s*const institutions/
  );
  const institutionsMatch = script.match(
    /const institutions = ([\s\S]*?);\r?\n\s*const institutionById/
  );
  if (!itemsMatch || !institutionsMatch) {
    throw new Error("search data assignments were not found");
  }

  const coreStart = script.indexOf("const SEARCH_SYNONYM_GROUPS");
  const coreEnd = script.indexOf("function institutionSearchScore", coreStart);
  if (coreStart < 0 || coreEnd <= coreStart) {
    throw new Error("search implementation was not found");
  }

  const source = `
    const items = ${itemsMatch[1]};
    const institutions = ${institutionsMatch[1]};
    const institutionById = new Map(institutions.map((item) => [item.id, item]));
    ${script.slice(coreStart, coreEnd)}
    globalThis.searchApi = {
      items,
      institutions,
      institutionSearchMatch,
      eventSearchMatch
    };
  `;
  const context = {};
  vm.runInNewContext(source, context, { timeout: 10000 });
  return context.searchApi;
}

function runSearch(api, query, options = {}) {
  const region = options.region || "서울";
  const eventTypes = options.eventTypes || ["전시"];
  const startedAt = Date.now();
  const institutions = api.institutions
    .filter((institution) => region === "all" || institution.region === region)
    .map((institution) => ({
      institution,
      match: api.institutionSearchMatch(institution, query),
    }))
    .filter((entry) => entry.match)
    .sort((left, right) => right.match.score - left.match.score);
  const events = api.items
    .filter((item) => region === "all" || item.region === region)
    .filter((item) => eventTypes.includes(item.type))
    .map((item) => ({ item, match: api.eventSearchMatch(item, query) }))
    .filter((entry) => entry.match)
    .sort((left, right) => right.match.score - left.match.score);
  return {
    institutions,
    events,
    elapsedMs: Date.now() - startedAt,
  };
}

function topInstitutionNames(result) {
  return result.institutions
    .slice(0, 5)
    .map((entry) => entry.institution.name);
}

function totalResults(result) {
  return result.institutions.length + result.events.length;
}

function assertIncludes(values, marker, label) {
  if (!values.some((value) => value.includes(marker))) {
    fail(`${label}: expected “${marker}”, got ${JSON.stringify(values)}`);
  }
}

function main() {
  if (!fs.existsSync(htmlPath)) {
    throw new Error(`HTML does not exist: ${htmlPath}`);
  }
  const api = extractSearchApi(fs.readFileSync(htmlPath, "utf8"));
  const tests = [];

  const koreanAlias = runSearch(api, "국현");
  const koreanAliasNames = topInstitutionNames(koreanAlias);
  assertIncludes(koreanAliasNames, "국립현대미술관", "Korean alias");
  if (koreanAliasNames.some((name) => !name.includes("국립현대미술관"))) {
    fail(`Korean alias included an unrelated institution: ${koreanAliasNames}`);
  }
  tests.push(["국현", koreanAlias]);

  const englishAlias = runSearch(api, "MMCA");
  assertIncludes(
    topInstitutionNames(englishAlias),
    "국립현대미술관",
    "English alias"
  );
  tests.push(["MMCA", englishAlias]);

  const typo = runSearch(api, "리움미술과");
  assertIncludes(topInstitutionNames(typo), "리움미술관", "One-letter typo");
  tests.push(["리움미술과", typo]);

  const combinedTopic = runSearch(api, "현대 사진");
  if (totalResults(combinedTopic) === 0) {
    fail("combined topic returned no results");
  }
  tests.push(["현대 사진", combinedTopic]);

  const familyCraft = runSearch(api, "아이와 공예");
  if (totalResults(familyCraft) === 0) {
    fail("synonym-based combined topic returned no results");
  }
  tests.push(["아이와 공예", familyCraft]);

  const ceramics = runSearch(api, "도자");
  if (totalResults(ceramics) === 0) {
    fail("ceramics synonym returned no results");
  }
  tests.push(["도자", ceramics]);

  const program = runSearch(api, "과학", {
    eventTypes: ["강연", "교육", "행사"],
  });
  if (program.events.length === 0) {
    fail("program search returned no results");
  }
  tests.push(["과학 (program)", program]);

  const unrelated = runSearch(api, "야구선수 이적시장");
  if (totalResults(unrelated) !== 0) {
    fail(
      `unrelated query returned ${totalResults(unrelated)} results`
    );
  }
  tests.push(["야구선수 이적시장", unrelated]);

  const slow = tests.filter(([, result]) => result.elapsedMs > 1500);
  if (slow.length) {
    fail(
      `search exceeded 1500ms: ${slow
        .map(([query, result]) => `${query}=${result.elapsedMs}ms`)
        .join(", ")}`
    );
  }

  tests.forEach(([query, result]) => {
    console.log(
      `${query}: institutions=${result.institutions.length}, ` +
        `events=${result.events.length}, elapsed=${result.elapsedMs}ms`
    );
  });
  if (!process.exitCode) console.log("search relevance audit: OK");
}

try {
  main();
} catch (error) {
  fail(error.stack || error.message);
}
