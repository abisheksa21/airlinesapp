import type { ReferenceProfile } from "../lib/reference-profiles";

export default function ReferencePanel({ profile }: { profile: ReferenceProfile }) {
  return (
    <div className="reference-panel">
      <div className="reference-panel-intro">
        <div>
          <p className="eyebrow">Reference context</p>
          <h2>{profile.name}</h2>
          <p className="reference-strapline">{profile.strapline}</p>
        </div>
        <span className="reference-badge">{profile.kind === "carrier" ? "Carrier profile" : "Airport profile"}</span>
      </div>

      <div className="reference-grid">
        <section className="reference-card reference-card-wide">
          <p className="reference-label">What this is</p>
          <p>{profile.whatItIs}</p>
        </section>
        <section className="reference-card">
          <p className="reference-label">Role</p>
          <p className="reference-role">{profile.role}</p>
          <dl className="reference-facts">
            {profile.quickFacts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}
          </dl>
        </section>
        <section className="reference-card">
          <p className="reference-label">Short history</p>
          <ol className="reference-timeline">
            {profile.history.map((item) => <li key={item}>{item}</li>)}
          </ol>
        </section>
        <section className="reference-card reference-card-wide">
          <p className="reference-label">How to read this profile</p>
          <ul className="reference-notes">
            {profile.operationalNotes.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      </div>

      <div className="reference-footer">
        <div>
          <p className="reference-label">Sources and boundaries</p>
          <p className="reference-boundary">Reference facts are kept separate from performance. Numbers on this site are calculated from the local BTS warehouse.</p>
        </div>
        <div className="reference-sources">
          {profile.sources.map((source) => <a key={source.href} href={source.href} target="_blank" rel="noreferrer">{source.label} ↗</a>)}
        </div>
      </div>
    </div>
  );
}
