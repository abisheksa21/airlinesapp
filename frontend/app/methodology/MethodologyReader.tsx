"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import MarkdownBody from "../components/MarkdownBody";

type TopicId = "health" | "decisions" | "models" | "supporting";

type MethodSection = {
  id: string;
  title: string;
  markdown: string;
};

type Topic = {
  id: TopicId;
  kicker: string;
  title: string;
  description: string;
  intros: string[];
  sections: MethodSection[];
};

const TOPIC_COPY: Record<
  TopicId,
  Pick<Topic, "kicker" | "title" | "description">
> = {
  health: {
    kicker: "01 · HISTORICAL SCORE",
    title: "Health Score",
    description:
      "What the score summarizes, how its ingredients are weighted, and how much confidence to place in it.",
  },
  decisions: {
    kicker: "02 · DECISION TOOLS",
    title: "Decision Center",
    description:
      "What each diagnostic or optimizer answers—and where a scenario stops short of an operational promise.",
  },
  models: {
    kicker: "03 · PREDICTION + T-100",
    title: "Forecasts and model evidence",
    description:
      "How traffic context is matched to flight outcomes and how richer models are checked on later data.",
  },
  supporting: {
    kicker: "04 · SUPPORTING METHODS",
    title: "Proxies and boundaries",
    description:
      "Supporting queue and delay-propagation methods, plus what the current system does not model.",
  },
};

const MODEL_SECTION_IDS = new Set([
  "t-100-and-on-time-correlation",
  "route-delay-forecast-baseline",
  "first-route-ml-candidate",
  "shared-route-panel-candidate",
  "repeated-temporal-validation",
]);

const SUPPORTING_SECTION_IDS = new Set([
  "supporting-queue-pressure-model",
  "supporting-markov-delay-propagation",
  "what-is-deliberately-not-modeled",
]);

function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function parseSections(content: string): Record<TopicId, Topic> {
  const topics: Record<TopicId, Topic> = {
    health: { id: "health", ...TOPIC_COPY.health, intros: [], sections: [] },
    decisions: {
      id: "decisions",
      ...TOPIC_COPY.decisions,
      intros: [],
      sections: [],
    },
    models: { id: "models", ...TOPIC_COPY.models, intros: [], sections: [] },
    supporting: {
      id: "supporting",
      ...TOPIC_COPY.supporting,
      intros: [],
      sections: [],
    },
  };

  const chapters = content.trim().split(/(?=^# (?!#).+$)/m);
  chapters.forEach((chapter, chapterIndex) => {
    const blocks = chapter.split(/(?=^## (?!#).+$)/m);
    const intro = blocks.shift()?.trim();
    const parsed = blocks.flatMap((block) => {
      const heading = /^## (.+)\r?$/m.exec(block);
      if (!heading) return [];
      const title = heading[1].trim();
      return [
        {
          id: slugify(title),
          title,
          markdown: block.replace(/^## .+\r?\n+/, "").trim(),
        },
      ];
    });

    const chapterTitle = /^# (.+)$/m.exec(intro ?? "")?.[1] ?? "";
    const chapterId = slugify(chapterTitle);
    const defaultTopic: TopicId =
      chapterIndex < 2
        ? "health"
        : chapterId === "decision-center-methodology"
          ? "decisions"
          : "supporting";

    if (intro) topics[defaultTopic].intros.push(intro);
    parsed.forEach((section) => {
      const topic: TopicId = SUPPORTING_SECTION_IDS.has(section.id)
        ? "supporting"
        : MODEL_SECTION_IDS.has(section.id)
          ? "models"
          : defaultTopic;
      topics[topic].sections.push(section);
    });
  });

  return topics;
}

export default function MethodologyReader({
  content,
}: {
  content: string;
}) {
  const topics = useMemo(() => parseSections(content), [content]);
  const topicIds = Object.keys(TOPIC_COPY) as TopicId[];
  const [activeTopic, setActiveTopic] = useState<TopicId>("health");
  const sectionsRef = useRef<HTMLDivElement>(null);

  const anchorTopics = useMemo(() => {
    const anchors: Record<string, TopicId> = {
      "method-details": "health",
    };
    Object.values(topics).forEach((topic) => {
      topic.intros.forEach((intro) => {
        const heading = /^# (.+)$/m.exec(intro)?.[1];
        if (heading) anchors[slugify(heading)] = topic.id;
      });
      topic.sections.forEach((section) => {
        anchors[section.id] = topic.id;
        for (const match of section.markdown.matchAll(/^#{3} (.+)$/gm)) {
          anchors[slugify(match[1])] = topic.id;
        }
      });
    });
    return anchors;
  }, [topics]);

  useEffect(() => {
    const selectTopicFromHash = () => {
      const id = decodeURIComponent(window.location.hash.slice(1));
      const topic = anchorTopics[id];
      if (topic) setActiveTopic(topic);
    };
    selectTopicFromHash();
    window.addEventListener("hashchange", selectTopicFromHash);
    return () => window.removeEventListener("hashchange", selectTopicFromHash);
  }, [anchorTopics]);

  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (!id || anchorTopics[id] !== activeTopic) return;

    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(id);
      if (!target) return;
      const details = target.closest("details");
      if (details instanceof HTMLDetailsElement) details.open = true;
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeTopic, anchorTopics]);

  const active = topics[activeTopic];

  function setAllSections(open: boolean) {
    sectionsRef.current
      ?.querySelectorAll<HTMLDetailsElement>("details")
      .forEach((section) => {
        section.open = open;
      });
  }

  return (
    <section className="methodology-reader" aria-label="Methodology guide">
      <div className="methodology-at-a-glance" aria-label="Choose a methodology topic">
        {topicIds.map((id) => {
          const topic = topics[id];
          return (
            <button
              key={id}
              type="button"
              aria-pressed={activeTopic === id}
              onClick={() => setActiveTopic(id)}
            >
              <span>{topic.kicker}</span>
              <strong>{topic.title}</strong>
              <small>{topic.description}</small>
            </button>
          );
        })}
      </div>

      <section className="methodology-topic-panel" id="method-details">
        <header className="methodology-topic-heading">
          <div>
            <span className="section-label">{active.kicker}</span>
            <h2>{active.title}</h2>
            <p>{active.description}</p>
          </div>
          <div className="methodology-section-actions">
            <span>{active.sections.length} sections</span>
            <button type="button" onClick={() => setAllSections(true)}>
              Expand all
            </button>
            <button type="button" onClick={() => setAllSections(false)}>
              Collapse all
            </button>
          </div>
        </header>

        {active.intros.map((intro) => (
          <div className="methodology-chapter-intro" key={intro.slice(0, 80)}>
            <MarkdownBody content={intro} headingAnchors />
          </div>
        ))}

        <div className="methodology-sections" ref={sectionsRef}>
          {active.sections.map((section, index) => (
            <details className="methodology-detail" key={section.id}>
              <summary id={section.id}>
                <span className="methodology-detail-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <strong>{section.title}</strong>
                <span className="methodology-detail-toggle" aria-hidden="true" />
              </summary>
              <div className="methodology-detail-body">
                <MarkdownBody content={section.markdown} headingAnchors />
              </div>
            </details>
          ))}
        </div>
      </section>
    </section>
  );
}
