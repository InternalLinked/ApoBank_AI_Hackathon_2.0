import { FormEvent, useState } from "react";
import type { ExtractedFinding, ManualEntryInput, PartnerSummary } from "@/lib/workspace-contracts";
import { errorMessage } from "@/lib/workspace-api";
import { Icon } from "./Icons";

type InspectorPanelProps = {
  partner: PartnerSummary | null;
  findings: ExtractedFinding[];
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onSaveEntry: (input: ManualEntryInput) => Promise<string>;
  onConfirmFindings: (findingIds: string[]) => void;
};

export function InspectorPanel({ partner, findings, mobileOpen, onCloseMobile, onSaveEntry, onConfirmFindings }: InspectorPanelProps) {
  const today = new Date().toISOString().slice(0, 10);
  const [activeTab, setActiveTab] = useState<"findings" | "manual">("findings");
  const [entryKind, setEntryKind] = useState<"partner" | "note">("partner");
  const [fileName, setFileName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState("");
  const [isError, setIsError] = useState(false);
  const pending = findings.filter((finding) => finding.status === "new");

  async function savePartner(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const label = await onSaveEntry({
        kind: "partner",
        name: String(form.get("name") ?? ""),
        company: String(form.get("company") ?? ""),
        relationshipManager: String(form.get("relationshipManager") ?? ""),
        email: String(form.get("email") ?? ""),
      });
      setIsError(false);
      setSuccess(`${label} wurde angelegt.`);
      event.currentTarget.reset();
    } catch (error) {
      setIsError(true);
      setSuccess(errorMessage(error, "Der Vermittler konnte nicht angelegt werden."));
    } finally {
      setSaving(false);
    }
  }

  async function saveNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const label = await onSaveEntry({
        kind: "note",
        partnerName: String(form.get("partnerName") ?? ""),
        date: String(form.get("date") ?? ""),
        content: String(form.get("content") ?? ""),
        fileName,
        file,
        vermittlerNr: partner?.vermittlerNr,
      });
      setIsError(false);
      setSuccess(`${label} wurde gespeichert.`);
      event.currentTarget.reset();
      setFileName("");
      setFile(null);
    } catch (error) {
      setIsError(true);
      setSuccess(errorMessage(error, "Die Notiz konnte nicht gespeichert werden."));
    } finally {
      setSaving(false);
    }
  }

  function openManual(kind: "partner" | "note") {
    setEntryKind(kind);
    setActiveTab("manual");
    setSuccess("");
  }

  return (
    <aside className="inspector-panel" data-mobile-open={mobileOpen} aria-label="Partnerakte und manuelle Eingabe">
      <div className="inspector-heading"><div><span className="eyebrow">PARTNERAKTE</span><h2>{partner?.name ?? "Noch keine Akte"}</h2><p>{partner ? <>{partner.company} <span>·</span> {partner.partnerId}</> : "Suche einen Vermittler im Chat oder lege ihn manuell an."}</p></div><button className="icon-button inspector-close" aria-label="Details schließen" onClick={onCloseMobile}><Icon name="close" /></button></div>
      {partner && <div className="partner-status-row"><span className="status-dot" />{partner.status}<span className="status-separator">·</span><span>Betreut von {partner.relationshipManager}</span></div>}

      <div className="inspector-tabs" role="tablist" aria-label="Partnerakten-Bereich">
        <button type="button" role="tab" aria-selected={activeTab === "findings"} className={activeTab === "findings" ? "is-active" : ""} onClick={() => setActiveTab("findings")}><Icon name="sparkle" size={15} />Erkannt{pending.length > 0 && <span className="tab-count">{pending.length}</span>}</button>
        <button type="button" role="tab" aria-selected={activeTab === "manual"} className={activeTab === "manual" ? "is-active" : ""} onClick={() => { setActiveTab("manual"); setSuccess(""); }}><Icon name="plus" size={15} />Manuell</button>
      </div>

      {activeTab === "findings" ? (
        <div className="inspector-scroll">
          <div className="section-title-row"><div><h3>Aus dem Chat erkannt</h3><p>Prüfe die Angaben, bevor sie gespeichert werden.</p></div><span className="source-count"><Icon name="file" size={14} />{findings.length} Angaben</span></div>
          {findings.length === 0 ? <div className="review-note"><Icon name="sparkle" size={15} /><p>Wenn der Copilot konkrete Angaben zu einer Partnerakte erkennt, erscheinen sie hier zur Bestätigung.</p></div> : <>

          <div className="finding-group"><div className="finding-group-heading"><span className="group-icon"><Icon name="person" size={15} /></span><h4>Partner & Gespräch</h4></div>{findings.filter((finding) => finding.group === "partner").map((finding) => <FindingRow key={finding.id} finding={finding} />)}</div>
          <div className="finding-group"><div className="finding-group-heading"><span className="group-icon blue"><Icon name="briefcase" size={15} /></span><h4>Geschäftsdaten</h4></div>{findings.filter((finding) => finding.group === "business").map((finding) => <FindingRow key={finding.id} finding={finding} />)}</div>
          <div className="finding-group"><div className="finding-group-heading"><span className="group-icon amber"><Icon name="calendar" size={15} /></span><h4>Nächster Schritt</h4></div>{findings.filter((finding) => finding.group === "next-step").map((finding) => <FindingRow key={finding.id} finding={finding} />)}</div>

          <div className="review-note"><Icon name="sparkle" size={15} /><p>Die Angaben stammen aus dem Chat. Vor dem Übernehmen bitte gegenprüfen.</p></div>
          <button type="button" className={`confirm-button ${pending.length === 0 ? "is-confirmed" : ""}`} disabled={pending.length === 0 || !partner} onClick={() => onConfirmFindings(pending.map((finding) => finding.id))}><Icon name="check" size={17} />{pending.length === 0 ? "Angaben übernommen" : `Alle ${pending.length} Angaben übernehmen`}</button>
          </>}
          <button type="button" className="secondary-wide-button" onClick={() => openManual("note")}><Icon name="note" size={16} />Gesprächsnotiz manuell ergänzen</button>
        </div>
      ) : (
        <div className="inspector-scroll manual-scroll">
          <div className="section-title-row"><div><h3>Eintrag erstellen</h3><p>Lege Informationen direkt in der Partnerakte an.</p></div></div>
          <div className="entry-type-switch" role="tablist" aria-label="Eintragstyp"><button className={entryKind === "partner" ? "is-active" : ""} onClick={() => { setEntryKind("partner"); setSuccess(""); }} type="button"><Icon name="person" size={15} />Vermittler</button><button className={entryKind === "note" ? "is-active" : ""} onClick={() => { setEntryKind("note"); setSuccess(""); }} type="button"><Icon name="note" size={15} />Gesprächsnotiz</button></div>
          {success && <div className={`success-banner ${isError ? "is-error" : ""}`} role={isError ? "alert" : "status"}><Icon name={isError ? "close" : "check"} size={16} />{success}</div>}
          {entryKind === "partner" ? (
            <form className="entry-form" onSubmit={savePartner}>
              <label>Vor- und Nachname<input name="name" placeholder="z. B. Alex Beispiel" required /></label>
              <label>Unternehmen<input name="company" placeholder="Name des Unternehmens" required /></label>
              <label>Betreuende Person<input name="relationshipManager" placeholder="Name der Betreuung" /></label>
              <label>E-Mail-Adresse<input name="email" type="email" placeholder="name@beispiel.de" /></label>
              <div className="form-footnote"><Icon name="clock" size={14} />Der Vermittler wird direkt in der Partnerdatenbank angelegt.</div>
              <button className="confirm-button" type="submit" disabled={saving}><Icon name="plus" size={17} />{saving ? "Wird gespeichert …" : "Vermittler anlegen"}</button>
            </form>
          ) : (
            <form className="entry-form" onSubmit={saveNote}>
              <label>Vermittler<input name="partnerName" defaultValue={partner?.name ?? ""} placeholder="Vor- und Nachname" required /></label>
              <label>Gesprächsdatum<input type="date" name="date" defaultValue={today} required /></label>
              <label>Gesprächsnotiz<textarea name="content" rows={6} placeholder="Themen, Entscheidungen und nächste Schritte …" required /></label>
              <label className="upload-field"><span>Dokument anhängen</span><div className="upload-control"><Icon name="upload" size={16} /><span>{fileName || "PDF, DOCX oder TXT auswählen"}</span><input type="file" accept=".pdf,.doc,.docx,.txt" onChange={(event) => { const selected = event.target.files?.[0] ?? null; setFile(selected); setFileName(selected?.name ?? ""); }} /></div></label>
              <div className="form-footnote"><Icon name="clock" size={14} />Die Notiz wird mit dem optionalen Anhang in der Partnerakte gespeichert.</div>
              <button className="confirm-button" type="submit" disabled={saving}><Icon name="plus" size={17} />{saving ? "Wird gespeichert …" : "Gesprächsnotiz speichern"}</button>
            </form>
          )}
        </div>
      )}
    </aside>
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
