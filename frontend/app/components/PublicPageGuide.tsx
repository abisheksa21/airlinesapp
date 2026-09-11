type PublicPageGuideProps = {
  topic: string;
  explanation: string;
  note: string;
};

export default function PublicPageGuide({ topic, explanation, note }: PublicPageGuideProps) {
  return (
    <aside className="public-page-guide" aria-label={`How to read the ${topic.toLowerCase()} page`}>
      <span className="public-page-guide-label">How to read this page</span>
      <p>{explanation}</p>
      <span className="public-page-guide-note">{note}</span>
    </aside>
  );
}
