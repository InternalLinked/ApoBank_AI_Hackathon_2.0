import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

// Erlaubte Link-Ziele: Web, E-Mail, Telefon und Obsidian-Deeplinks. Alles andere (javascript: …) wird entfernt.
const ALLOWED_PROTOCOLS = /^(https?:|mailto:|tel:|obsidian:)/i;

function urlTransform(url: string): string {
  if (ALLOWED_PROTOCOLS.test(url)) return url;
  return defaultUrlTransform(url);
}

/**
 * Rendert Copilot-Antworten als Markdown: Überschriften, Fett/Kursiv, Listen, Tabellen, Zitate als Hinweise
 * und klickbare Links. Rohes HTML wird nicht ausgeführt (react-markdown escaped es).
 */
export function MessageMarkdown({ content }: { content: string }) {
  return (
    <div className="message-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        components={{
          a: ({ href, children }) => {
            if (!href) return <>{children}</>; // blockiertes Ziel (z. B. javascript:) als reiner Text
            const external = typeof href === "string" && /^https?:/i.test(href);
            return (
              <a href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                className={typeof href === "string" && href.startsWith("obsidian:") ? "md-link md-link-obsidian" : "md-link"}>
                {children}
              </a>
            );
          },
          table: ({ children }) => <div className="md-table-wrap"><table>{children}</table></div>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
