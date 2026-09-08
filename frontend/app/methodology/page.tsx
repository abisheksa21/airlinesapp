import fs from "fs";
import path from "path";
import MarkdownBody from "../components/MarkdownBody";

export default function MethodologyPage() {
  const filePath = path.join(process.cwd(), "app", "methodology", "content.md");
  const content = fs.readFileSync(filePath, "utf-8");

  return (
    <main className="page">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Methodology</p>
        <h1 className="title">How the analysis works</h1>
        <p className="subtitle">
          Plain-language explanations first, then the full formulas for the Health Score and Decision Center.
        </p>
      </header>

      <section className="section">
        <div className="screen markdown-page">
          <MarkdownBody content={content} />
        </div>
      </section>
    </main>
  );
}
