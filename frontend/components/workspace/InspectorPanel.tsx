import { FormEvent, useState } from "react";
import type { ExtractedFinding, ManualEntryInput, PartnerDetail, PartnerSummary } from "@/lib/workspace-contracts";
import { Icon } from "./Icons";

type InspectorPanelProps = {
  partner: PartnerSummary | null;
  partnerDetail: PartnerDetail | null;
  findings: ExtractedFinding[];
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onSaveEntry: (input: ManualEntryInput) => Promise<string>;
  onConfirmFindings: (findingIds: string[]) => void;
};

export function InspectorPanel({ partner, partnerDetail, findings, mobileOpen, onCloseMobile, onSaveEntry, onConfirmFindings }: InspectorPanelProps) {
  const today = new Date().toISOString().slice(0, 10);
  const [addOpen, setAddOpen] = useState(false);
  const [entryKind, setEntryKind] = useState<"partner" | "note">("partner");
  const [fileName, setFileName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const pending = findings.filter((finding) => finding.status === "new");

  function openAdd(kind?: "partner" | "note") {
    setEntryKind(kind ?? (partner ? "note" : "partner"));
    setFileName("");
    setFile(null);
    setFeedback("");
    setAddOpen(true);
  }

  function closeAdd() {
    if (!saving) setAddOpen(false);
  }

  async function savePartner(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setSaving(true);
    setFeedback("");
    try {
      await onSaveEntry({
        kind: "partner",
        name: String(form.get("name") ?? ""),
        company: String(form.get("company") ?? ""),
        relationshipManager: "",
        email: String(form.get("email") ?? ""),
      });
      formElement.reset();
      setAddOpen(false);
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Der Vermittler konnte nicht angelegt werden.");
    } finally {
      setSaving(false);
    }
  }

  async function saveNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setSaving(true);
    setFeedback("");
    const partnerName = String(form.get("partnerName") ?? "");
    const selectedPartnerMatches = partner?.name.trim().toLocaleLowerCase("de-DE") === partnerName.trim().toLocaleLowerCase("de-DE");
    try {
      await onSaveEntry({
        kind: "note",
        partnerName,
        date: String(form.get("date") ?? ""),
        title: String(form.get("title") ?? "Gesprächsnotiz"),
        content: String(form.get("content") ?? ""),
        participants: String(form.get("participants") ?? ""),
        nextSteps: String(form.get("nextSteps") ?? ""),
        fileName,
        file,
        vermittlerNr: selectedPartnerMatches ? partner?.vermittlerNr : undefined,
      });
      formElement.reset();
      setFileName("");
      setFile(null);
      setAddOpen(false);
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Die Gesprächsnotiz konnte nicht gespeichert werden.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <aside className="inspector-panel" data-mobile-open={mobileOpen} aria-label="Partnerakte">
      <div className="inspector-heading">
        <div>
          <span className="eyebrow">PARTNERAKTE</span>
          <h2>{partner?.name ?? "Noch keine Akte"}</h2>
          <p>{partner ? <>{partner.company} <span>·</span> {partner.partnerId}</> : "Suche einen Vermittler im Chat oder lege ihn selbst an."}</p>
        </div>
        <div className="inspector-actions">
          <button className="add-entry-button" type="button" onClick={() => openAdd()}><Icon name="plus" size={16} /><span>Hinzufügen</span></button>
          <button className="icon-button inspector-close" aria-label="Details schließen" onClick={onCloseMobile}><Icon name="close" /></button>
        </div>
      </div>
      {partner && <div className="partner-status-row"><span className="status-dot" />{partner.status}<span className="status-separator">·</span><span>Betreut von {partner.relationshipManager}</span></div>}

      {partnerDetail && <section className="partner-profile" aria-label="Daten aus der Partnerdatenbank">
        <div className="partner-profile-heading"><h3>Partnerprofil</h3><span>Live aus Datenbank</span></div>
        <dl>
          <div><dt>Vermittler-ID</dt><dd>{partnerDetail.partnerId}</dd></div>
          <div><dt>Unternehmen</dt><dd>{partnerDetail.company}</dd></div>
          {partnerDetail.location && <div><dt>Standort</dt><dd>{partnerDetail.location}</dd></div>}
          {partnerDetail.email && <div><dt>E-Mail</dt><dd className="email-value"><span title={partnerDetail.email}>{partnerDetail.email}</span><CopyButton value={partnerDetail.email} label="E-Mail-Adresse kopieren" /></dd></div>}
          {partnerDetail.branch && <div><dt>Filiale</dt><dd>{partnerDetail.branch}{partnerDetail.marketArea ? ` · ${partnerDetail.marketArea}` : ""}</dd></div>}
        </dl>
        {partnerDetail.businessFigures[0] && <div className="partner-figure"><span>Volumen {partnerDetail.businessFigures[0].year}</span><strong>{new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(partnerDetail.businessFigures[0].volume)}</strong><small>{partnerDetail.businessFigures[0].loanCount} Darlehen</small></div>}
        {partnerDetail.interests.length > 0 && <div className="partner-tags">{partnerDetail.interests.slice(0, 3).map((interest) => <span key={interest}>{interest}</span>)}</div>}
      </section>}

      <div className="inspector-tabs inspector-tabs-single" aria-label="Partnerakten-Bereich">
        <span><Icon name="sparkle" size={15} />Aus dem Chat erkannt{pending.length > 0 && <span className="tab-count">{pending.length}</span>}</span>
      </div>

      <div className="inspector-scroll">
        <div className="section-title-row"><div><h3>Aus dem Chat erkannt</h3><p>Prüfe die Angaben, bevor sie gespeichert werden.</p></div><span className="source-count"><Icon name="file" size={14} />{findings.length} Angaben</span></div>
        {findings.length === 0 ? <div className="review-note"><Icon name="sparkle" size={15} /><p>Wenn der Copilot konkrete Angaben zu einer Partnerakte erkennt, erscheinen sie hier zur Bestätigung.</p></div> : <>
          <div className="finding-group"><div className="finding-group-heading"><span className="group-icon"><Icon name="person" size={15} /></span><h4>Partner & Gespräch</h4></div>{findings.filter((finding) => finding.group === "partner").map((finding) => <FindingRow key={finding.id} finding={finding} />)}</div>
          <div className="finding-group"><div className="finding-group-heading"><span className="group-icon blue"><Icon name="briefcase" size={15} /></span><h4>Geschäftsdaten</h4></div>{findings.filter((finding) => finding.group === "business").map((finding) => <FindingRow key={finding.id} finding={finding} />)}</div>
          <div className="finding-group"><div className="finding-group-heading"><span className="group-icon amber"><Icon name="calendar" size={15} /></span><h4>Nächster Schritt</h4></div>{findings.filter((finding) => finding.group === "next-step").map((finding) => <FindingRow key={finding.id} finding={finding} />)}</div>
          <div className="review-note"><Icon name="sparkle" size={15} /><p>Die Angaben stammen aus dem Chat. Vor dem Übernehmen bitte gegenprüfen.</p></div>
          <button type="button" className={`confirm-button ${pending.length === 0 ? "is-confirmed" : ""}`} disabled={pending.length === 0 || !partner} onClick={() => onConfirmFindings(pending.map((finding) => finding.id))}><Icon name="check" size={17} />{pending.length === 0 ? "Angaben übernommen" : `Alle ${pending.length} Angaben übernehmen`}</button>
        </>}
      </div>

      {addOpen && <div className="add-entry-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeAdd(); }}>
        <section className="add-entry-dialog" role="dialog" aria-modal="true" aria-labelledby="add-entry-title">
          <div className="add-entry-header">
            <div><span className="eyebrow">MANUELL HINZUFÜGEN</span><h3 id="add-entry-title">Was möchtest du anlegen?</h3><p>Lege Vermittlerdaten, Gesprächsinhalte und optionale Dokumente direkt ab.</p></div>
            <button type="button" className="icon-button" aria-label="Dialog schließen" onClick={closeAdd} disabled={saving}><Icon name="close" /></button>
          </div>
          <div className="entry-type-switch" role="tablist" aria-label="Eintragstyp">
            <button className={entryKind === "partner" ? "is-active" : ""} onClick={() => { setEntryKind("partner"); setFeedback(""); }} type="button"><Icon name="person" size={16} /><span><strong>Vermittler</strong><small>Partnerakte anlegen</small></span></button>
            <button className={entryKind === "note" ? "is-active" : ""} onClick={() => { setEntryKind("note"); setFeedback(""); }} type="button"><Icon name="note" size={16} /><span><strong>Gespräch & Dokument</strong><small>Notiz oder Anhang speichern</small></span></button>
          </div>
          {feedback && <div className="form-feedback" role="alert">{feedback}</div>}
          {entryKind === "partner" ? (
            <form className="entry-form" onSubmit={savePartner}>
              <label>Vor- und Nachname<input name="name" placeholder="z. B. Alex Beispiel" required /></label>
              <label>Unternehmen<input name="company" placeholder="Name des Unternehmens" required /></label>
              <label>E-Mail-Adresse <span className="optional">optional</span><input name="email" type="email" placeholder="name@beispiel.de" /></label>
              <div className="form-footnote"><Icon name="clock" size={14} />Der Vermittler wird direkt in der Partnerdatenbank angelegt.</div>
              <button className="confirm-button" type="submit" disabled={saving}><Icon name="plus" size={17} />{saving ? "Wird gespeichert …" : "Vermittler anlegen"}</button>
            </form>
          ) : (
            <form className="entry-form" onSubmit={saveNote}>
              <div className="form-two-columns"><label>Vermittler<input name="partnerName" defaultValue={partner?.name ?? ""} placeholder="Vor- und Nachname" required /></label><label>Gesprächsdatum<input type="date" name="date" defaultValue={today} required /></label></div>
              <label>Titel<input name="title" defaultValue="Gesprächsnotiz" placeholder="z. B. Jahresgespräch" required /></label>
              <label>Teilnehmende <span className="optional">optional</span><input name="participants" placeholder="Namen mit Komma trennen" /></label>
              <label>Gesprächsnotiz<textarea name="content" rows={5} placeholder="Themen, Entscheidungen und wichtige Informationen …" required /></label>
              <label>Nächste Schritte <span className="optional">eine Zeile pro Maßnahme</span><textarea name="nextSteps" rows={3} placeholder={"Termin mit Partner vereinbaren\nUnterlagen nachreichen"} /></label>
              <label className="upload-field"><span>Dokument anhängen <span className="optional">optional</span></span><div className="upload-control"><Icon name="upload" size={16} /><span>{fileName || "PDF, DOC, DOCX oder TXT auswählen"}</span><input type="file" accept=".pdf,.doc,.docx,.txt" onChange={(event) => { const selected = event.target.files?.[0] ?? null; setFile(selected); setFileName(selected?.name ?? ""); }} /></div></label>
              <div className="form-footnote"><Icon name="clock" size={14} />Notiz, Teilnehmende, Maßnahmen und der optionale Anhang werden in der Partnerakte gespeichert.</div>
              <button className="confirm-button" type="submit" disabled={saving}><Icon name="plus" size={17} />{saving ? "Wird gespeichert …" : "In Partnerakte speichern"}</button>
            </form>
          )}
        </section>
      </div>}
    </aside>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const helper = document.createElement("textarea");
      helper.value = value;
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button type="button" className={`copy-button ${copied ? "is-copied" : ""}`} onClick={copy} aria-label={label} title={copied ? "Kopiert" : label}>
      <Icon name={copied ? "check" : "copy"} size={12} />
    </button>
  );
}

function FindingRow({ finding }: { finding: ExtractedFinding }) {
  return (
    <div className={`finding-row ${finding.status === "confirmed" ? "is-confirmed" : ""}`}>
      <div><span>{finding.label}</span><strong>{finding.value}</strong><small><Icon name="file" size={12} />{finding.source}</small></div>
      <span className="finding-status" title={finding.status === "confirmed" ? "Übernommen" : "Noch zu prüfen"}>{finding.status === "confirmed" ? <Icon name="check" size={13} /> : <span />}</span>
    </div>
  );
}
