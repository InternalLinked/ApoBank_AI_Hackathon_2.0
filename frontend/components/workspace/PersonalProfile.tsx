import { FormEvent, useEffect, useState } from "react";
import { errorMessage } from "@/lib/workspace-api";
import type { PersonalProfile as Profile, ProfileCategory, WorkspaceApi } from "@/lib/workspace-contracts";
import { Icon } from "./Icons";

const CATEGORY_ORDER: ProfileCategory[] = ["familie", "haustiere", "hobbys", "reisen", "vorlieben", "termine", "sonstiges"];

const CATEGORY_LABELS: Record<ProfileCategory, string> = {
  familie: "Familie",
  haustiere: "Haustiere",
  hobbys: "Hobbys & Freizeit",
  reisen: "Reisen & Urlaub",
  vorlieben: "Vorlieben & Gesprächsstil",
  termine: "Wichtige Daten",
  sonstiges: "Sonstiges",
};

type PersonalProfileProps = {
  api: WorkspaceApi;
  vermittlerNr: number;
  partnerName: string;
  /** Hochzählen, um das Profil neu zu laden (z. B. nach übernommenen Chat-Angaben). */
  refreshKey: number;
  onError: (message: string) => void;
  /** Wird nach dem Hinzufügen/Entfernen einer Info aufgerufen (z. B. um den Graphen neu zu laden). */
  onChanged?: () => void;
};

function formatDate(value: string | null): string {
  if (!value) return "";
  const [year, month, day] = value.split("-");
  return `${day}.${month}.${year}`;
}

/** Persönliches Profil aus Obsidian: kurze Infos für den Gesprächseinstieg (Familie, Haustiere, Urlaub …). */
export function PersonalProfile({ api, vermittlerNr, partnerName, refreshKey, onError, onChanged }: PersonalProfileProps) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [category, setCategory] = useState<ProfileCategory | "">("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.getProfile(vermittlerNr)
      .then((loaded) => { if (active) setProfile(loaded); })
      .catch((error) => { if (active) onError(errorMessage(error, "Das persönliche Profil konnte nicht geladen werden.")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // onError ist bewusst nicht in den Abhängigkeiten (neue Funktion bei jedem Render).
  }, [api, vermittlerNr, refreshKey]);

  async function addFact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    setSaving(true);
    try {
      const fact = await api.addProfileFact(vermittlerNr, value, category || undefined);
      setProfile((current) => current ? { ...current, facts: [...current.facts, fact] } : current);
      setText("");
      setCategory("");
      onChanged?.();
    } catch (error) {
      onError(errorMessage(error, "Die Info konnte nicht gespeichert werden."));
    } finally {
      setSaving(false);
    }
  }

  async function removeFact(factId: string) {
    try {
      await api.deleteProfileFact(vermittlerNr, factId);
      setProfile((current) => current ? { ...current, facts: current.facts.filter((fact) => fact.id !== factId) } : current);
      onChanged?.();
    } catch (error) {
      onError(errorMessage(error, "Die Info konnte nicht entfernt werden."));
    }
  }

  const facts = profile?.facts ?? [];
  const knownCategories = new Set<string>(CATEGORY_ORDER);
  const groups = [
    ...CATEGORY_ORDER.map((key) => ({ key, label: CATEGORY_LABELS[key] })),
    // Von Hand in Obsidian angelegte Überschriften ebenfalls anzeigen
    ...[...new Set(facts.map((fact) => fact.category))].filter((key) => !knownCategories.has(key))
      .map((key) => ({ key, label: facts.find((fact) => fact.category === key)?.categoryLabel ?? key })),
  ].map((group) => ({ ...group, facts: facts.filter((fact) => fact.category === group.key) }))
    .filter((group) => group.facts.length > 0);

  return (
    <section className="personal-profile" aria-label="Persönliches Profil">
      <div className="partner-profile-heading">
        <h3>Persönliches Profil</h3>
        {profile?.obsidianUri && <a className="obsidian-link" href={profile.obsidianUri} title="Profil-Notiz in Obsidian öffnen">In Obsidian öffnen</a>}
      </div>

      {loading ? <p className="personal-profile-empty">Profil wird geladen …</p>
        : groups.length === 0 ? <p className="personal-profile-empty">Noch nichts Persönliches zu {partnerName} notiert. Zum Beispiel: Urlaub, Familie, Haustiere oder Hobbys.</p>
        : <div className="personal-profile-groups">
          {groups.map((group) => (
            <div key={group.key} className="personal-profile-group">
              <h4>{group.label}</h4>
              <ul>
                {group.facts.map((fact) => (
                  <li key={fact.id}>
                    <span>{fact.text}{fact.date && <small>{formatDate(fact.date)}</small>}</span>
                    <button type="button" className="icon-button" aria-label={`„${fact.text}“ entfernen`} title="Entfernen" onClick={() => void removeFact(fact.id)}><Icon name="close" size={12} /></button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>}

      <form className="personal-profile-form" onSubmit={addFact}>
        <input value={text} onChange={(event) => setText(event.target.value)} maxLength={500} placeholder="z. B. Hat einen Hund namens Tim" aria-label="Persönliche Info" />
        <div>
          <select value={category} onChange={(event) => setCategory(event.target.value as ProfileCategory | "")} aria-label="Kategorie">
            <option value="">Kategorie automatisch</option>
            {CATEGORY_ORDER.map((key) => <option key={key} value={key}>{CATEGORY_LABELS[key]}</option>)}
          </select>
          <button type="submit" className="add-entry-button" disabled={saving || !text.trim()}><Icon name="plus" size={14} /><span>{saving ? "Speichert …" : "Notieren"}</span></button>
        </div>
      </form>
    </section>
  );
}
