import fs from "fs";
import path from "path";
import MethodologyReader from "./MethodologyReader";

export default function MethodologyPage() {
  const filePath = path.join(process.cwd(), "app", "methodology", "content.md");
  const content = fs.readFileSync(filePath, "utf-8");

  return (
    <main className="public-page public-reference-page methodology-page">
      <header className="public-reference-hero">
        <span className="section-label">Reference / methods</span>
        <h1>How each result is built.</h1>
        <p>Choose a topic. Start with the plain-language answer; expand a section only when you want the formulas, checks, and assumptions.</p>
        <div><span>Historical DOT / BTS records</span><span>Descriptive · predictive · what-if</span><span>Association is not causation</span></div>
      </header>
      <MethodologyReader content={content} />
    </main>
  );
}
