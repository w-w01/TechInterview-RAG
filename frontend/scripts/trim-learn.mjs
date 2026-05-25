import fs from "fs";

const p = "components/learn/LearnClient.tsx";
const L = fs.readFileSync(p, "utf8").split(/\r?\n/);

const practiceIdx = L.findIndex((l) => l.includes("mainTab === \"practice\""));
const learnIdx = L.findIndex((l) => l.includes("mainTab === \"learn\""));
console.log(practiceIdx, learnIdx);
if (practiceIdx >= 0 && learnIdx > practiceIdx) {
  L.splice(practiceIdx, learnIdx - practiceIdx);
}

const learnIdx2 = L.findIndex((l) => l.includes('mainTab === "learn"'));
if (learnIdx2 >= 0) {
  L[learnIdx2] = "          <>";
}

fs.writeFileSync(p, L.join("\n"), "utf8");
console.log("lines", L.length);
