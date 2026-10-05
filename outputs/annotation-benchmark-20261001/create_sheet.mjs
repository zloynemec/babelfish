import fs from "node:fs/promises";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const dir = new URL(".", import.meta.url);
const read = async (name) => JSON.parse(await fs.readFile(new URL(name, dir), "utf8"));
const results = await read("results.json");
const sample = await read("sample.json");
const judgments = await read("judgments.json");

const median = (values) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Сравнение");
const header = [
  "Сайт",
  "Аннотация ИИШКО",
  "Время ИИШКО, с",
  "Аннотация Qwen",
  "Время Qwen, с",
  "Победитель по качеству",
  "Основание выбора",
];
const rows = results.map((r) => {
  const i = r.iishko ?? {};
  const q = r.qwen_local ?? {};
  const judgment = judgments[r.url] ?? {};
  return [
    r.url,
    i.annotation ?? (i.error ? `Ошибка: ${i.error}` : "Нет ответа"),
    i.annotation ? i.seconds : null,
    q.annotation ?? (q.error ? `Ошибка: ${q.error}` : "Нет ответа"),
    q.annotation ? q.seconds : null,
    i.annotation && q.annotation ? (judgment.winner ?? "Не оценено") : "Нет сравнения",
    i.annotation && q.annotation ? (judgment.reason ?? "") : "ИИШКО не вернул аннотацию",
  ];
});
sheet.getRange(`A1:G${rows.length + 1}`).values = [header, ...rows];
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.getRange("A1:G1").format = {
  fill: "#17365D",
  font: { name: "Arial", size: 11, bold: true, color: "#FFFFFF" },
  rowHeight: 34,
  wrapText: true,
};
sheet.getRange(`A2:G${rows.length + 1}`).format = {
  font: { name: "Arial", size: 10, color: "#1F2937" },
  rowHeight: 84,
  wrapText: true,
  verticalAlignment: "top",
};
for (const [column, width] of Object.entries({ A: 32, B: 68, C: 18, D: 68, E: 18, F: 22, G: 50 })) {
  sheet.getRange(`${column}:${column}`).format.columnWidth = width;
}
sheet.getRange(`C2:C${rows.length + 1}`).format.numberFormat = "0.000";
sheet.getRange(`E2:E${rows.length + 1}`).format.numberFormat = "0.000";
sheet.tables.add(`A1:G${rows.length + 1}`, true, "AnnotationComparison");

const summary = workbook.worksheets.add("Методика и итоги");
summary.showGridLines = false;
const pairs = results.filter((r) => r.iishko?.annotation && r.qwen_local?.annotation);
const successesI = results.filter((r) => r.iishko?.annotation);
const successesQ = results.filter((r) => r.qwen_local?.annotation);
const winnerCount = (name) => rows.filter((r) => r[5] === name).length;
const attempted = sample.attempted.length;
const info = [
  ["Показатель", "Значение"],
  ["Сайтов в таблице", results.length],
  ["Доступных пар для оценки", pairs.length],
  ["Успешных ответов ИИШКО", successesI.length],
  ["Ответов Qwen", successesQ.length],
  ["Побед ИИШКО", winnerCount("ИИШКО")],
  ["Побед Qwen", winnerCount("Qwen")],
  ["Ничья", winnerCount("Ничья")],
  ["Медиана ИИШКО, с (успешные)", median(successesI.map((r) => r.iishko.seconds))],
  ["Медиана Qwen, с (успешные)", median(successesQ.map((r) => r.qwen_local.seconds))],
  ["Случайный seed", 20261001],
  ["Попыток загрузки сайтов", attempted],
  ["Выборка", "Первые 50 доступных страниц из случайной перестановки 1000 URL из файла runet_top1000.xlsx"],
  ["Вход моделям", "Один и тот же извлечённый текст до 20 000 символов; HTML, скрипты и служебные блоки удалены"],
  ["Измерение времени", "Только вызов провайдера, без загрузки сайта; секунды, wall clock"],
  ["ИИШКО", "qwen3.8-flash, API reformboss.com"],
  ["Qwen", "Qwen3-4B Q4_K_M, llama.cpp на этом Mac, reasoning off, 2 параллельных слота (8K, затем 16K токенов на слот)"],
  ["Ограничение", "Часть вызовов ИИШКО получила 400 Arrearage; для них победитель не назначен"],
  ["Нарушение формата 2–3 предложения у Qwen", 3],
];
summary.getRange(`A1:B${info.length}`).values = info;
summary.freezePanes.freezeRows(1);
summary.getRange("A1:B1").format = {
  fill: "#17365D",
  font: { name: "Arial", size: 11, bold: true, color: "#FFFFFF" },
};
summary.getRange(`A2:B${info.length}`).format = {
  font: { name: "Arial", size: 11, color: "#1F2937" },
  rowHeight: 34,
  wrapText: true,
};
summary.getRange("A:A").format.columnWidth = 37;
summary.getRange("B:B").format.columnWidth = 95;

const output = await SpreadsheetFile.exportXlsx(workbook);
const outputPath = new URL("annotation-comparison.xlsx", dir);
await output.save(outputPath.pathname);
const check = await workbook.inspect({kind: "region", sheetId: "Сравнение", range: "A1:G4", maxChars: 3000});
console.log(JSON.stringify({output: outputPath.pathname, rows: rows.length, pairs: pairs.length, check}));
