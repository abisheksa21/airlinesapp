import fs from "fs";
import path from "path";
import MarkdownBody from "../components/MarkdownBody";

export default function GlossaryPage() {
  const filePath = path.join(process.cwd(), "app", "glossary", "content.md");
  const content = fs.readFileSync(filePath, "utf-8");

  return (
    <main className="public-page public-reference-page">
      <header className="public-reference-hero">
        <span className="section-label">Reference / glossary</span>
        <h1>A common language for the network.</h1>
        <p>Every operational term used in the public brief and researcher workspace is defined once here—so a “delay,” “on-time,” or “connection score” never means different things on different pages.</p>
        <div><span>Plain-language definitions</span><span>Linked from evidence views</span><span>Built around BTS fields</span></div>
      </header>
      <section className="public-reference-layout">
        <aside><span className="section-label">How to use it</span><p>Definitions explain the terminology; they do not change the source data, model scope, or analytical caveats. For those, use Methodology.</p><a href="/methodology">Open methodology →</a></aside>
        <div className="public-markdown"><MarkdownBody content={content} /></div>
      </section>
    </main>
  );
}
