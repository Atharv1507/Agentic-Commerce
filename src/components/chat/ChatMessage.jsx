import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const MARKDOWN_COMPONENTS = {
  p: ({ children }) => <p className="[&:not(:first-child)]:mt-2">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="underline underline-offset-2">
      {children}
    </a>
  ),
  ul: ({ children }) => <ul className="mt-2 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mt-2 list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  h1: ({ children }) => <h1 className="mt-2 text-lg font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-2 text-base font-semibold">{children}</h3>,
  code: ({ children }) => <code className="rounded bg-black/20 px-1.5 py-0.5 text-sm">{children}</code>,
  blockquote: ({ children }) => (
    <blockquote className="mt-2 border-l-2 border-border pl-3 text-muted-foreground">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-border" />,
};

// A single centered column, not a left/right two-lane chat: the agent's
// reply spans the full width for readability, while the user's own messages
// stay narrower and lean right so the two are still easy to tell apart.
export default function ChatMessage({ message }) {
  const isAgent = message.role === "agent";

  if (isAgent) {
    return (
      <div
        className="w-full rounded-2xl border border-primary/10 px-5 py-4 text-base leading-relaxed"
        style={{ backgroundColor: "color-mix(in oklch, var(--color-card), var(--color-primary) 7%)" }}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {message.content || ""}
        </ReactMarkdown>
      </div>
    );
  }

  return (
    <div className="flex w-full justify-end">
      <div className="max-w-[70%] rounded-2xl rounded-br-md bg-primary px-5 py-3.5 text-base leading-relaxed text-primary-foreground">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {message.content || ""}
        </ReactMarkdown>
      </div>
    </div>
  );
}
