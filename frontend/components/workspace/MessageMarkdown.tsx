import type React from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

// Erlaubte Link-Ziele: Web, E-Mail, Telefon und Obsidian-Deeplinks. Alles andere (javascript: …) wird entfernt.
const ALLOWED_PROTOCOLS = /^(https?:|mailto:|tel:|obsidian:)/i;
// Vom Backend gesetzte Links auf Partnerakten: [Jens Weber](partner:1060)
const PARTNER_LINK = /^partner:(\d+)$/;

function urlTransform(url: string): string {
  if (ALLOWED_PROTOCOLS.test(url) || PARTNER_LINK.test(url)) return url;
  return defaultUrlTransform(url);
}

/**
 * Rendert Copilot-Antworten als Markdown: Überschriften, Fett/Kursiv, Listen, Tabellen, Zitate als Hinweise
 * und klickbare Links. Rohes HTML wird nicht ausgeführt (react-markdown escaped es).
 */
type MessageMarkdownProps = {
  content: string;
  /** Öffnet die Partnerakte, wenn ein verlinkter Vermittlername angeklickt wird. */
  onOpenPartner?: (vermittlerNr: number, name: string) => void;
};

function textOf(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(textOf).join("");
  if (children && typeof children === "object" && "props" in children) return textOf((children as { props: { children?: React.ReactNode } }).props.children);
  return "";
}

export function MessageMarkdown({ content, onOpenPartner }: MessageMarkdownProps) {
  return (
    <div className="message-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        components={{
          a: ({ href, children }) => {
            if (!href) return <>{children}</>; // blockiertes Ziel (z. B. javascript:) als reiner Text
            const partner = PARTNER_LINK.exec(href);
            if (partner) {
              const nr = Number(partner[1]);
              const name = textOf(children);
              return (
                <button type="button" className="md-partner-link" title={`Partnerakte von ${name} öffnen (VM-${nr})`}
                  onClick={() => onOpenPartner?.(nr, name)} disabled={!onOpenPartner}>
                  {children}
                </button>
              );
            }
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
