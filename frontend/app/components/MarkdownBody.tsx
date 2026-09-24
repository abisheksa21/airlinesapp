"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Children, isValidElement, type ReactNode } from "react";

function textFromChildren(children: ReactNode): string {
  return Children.toArray(children)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") {
        return String(child);
      }
      if (isValidElement<{ children?: ReactNode }>(child)) {
        return textFromChildren(child.props.children);
      }
      return "";
    })
    .join("");
}

function headingId(children: ReactNode): string {
  return textFromChildren(children)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export default function MarkdownBody({
  content,
  headingAnchors = false,
}: {
  content: string;
  headingAnchors?: boolean;
}) {
  const components = headingAnchors
    ? {
        h1: ({ children }: { children?: ReactNode }) => (
          <h1 id={headingId(children)}>{children}</h1>
        ),
        h2: ({ children }: { children?: ReactNode }) => (
          <h2 id={headingId(children)}>{children}</h2>
        ),
        h3: ({ children }: { children?: ReactNode }) => (
          <h3 id={headingId(children)}>{children}</h3>
        ),
      }
    : undefined;

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
}
