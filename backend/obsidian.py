"""Obsidian-"Gehirn" je Vermittler.

Aufbau im Vault (ein Vault fuer alle, ein Ordner pro Vermittler):

    vault/
      Vermittler/
        VM-4251/
          VM-4251.md                 <- Hub-Notiz (Frontmatter + verwaltete Bloecke + freie Notizen)
          Eintraege/
            2026-11-27_143005_gespraech_jahresgespraech.md

Bereiche zwischen ``<!-- BEGIN:x -->`` und ``<!-- END:x -->`` werden vom Backend
verwaltet und bei jedem Sync neu geschrieben. Alles andere (z. B. "Freie Notizen")
bleibt unangetastet, sodass Menschen parallel in Obsidian arbeiten koennen.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .config import settings

EINTRAG_TYPEN: dict[str, str] = {
    "gespraech": "Gesprächsprotokoll",
    "telefonat": "Telefonat",
    "email": "E-Mail",
    "notiz": "Notiz",
    "massnahme": "Maßnahme",
    "dokument": "Dokument",
    "sonstiges": "Sonstiges",
}

_BLOCK_RE = "<!-- BEGIN:{name} -->.*?<!-- END:{name} -->"


# --------------------------------------------------------------------------- Pfade

def note_name(vermittler_nr: int) -> str:
    return f"VM-{vermittler_nr}"


def folder_rel(vermittler_nr: int) -> str:
    return f"Vermittler/{note_name(vermittler_nr)}"


def hub_rel(vermittler_nr: int) -> str:
    return f"{folder_rel(vermittler_nr)}/{note_name(vermittler_nr)}.md"


def obsidian_uri(rel_path: str) -> str:
    file_ref = rel_path[:-3] if rel_path.endswith(".md") else rel_path
    return f"obsidian://open?vault={quote(settings.vault_name)}&file={quote(file_ref)}"


def abs_path(rel_path: str) -> Path:
    vault = Path(settings.vault_path).resolve()
    p = (vault / rel_path).resolve()
    if vault != p and vault not in p.parents:
        raise ValueError(f"Pfad ausserhalb des Vaults: {rel_path}")
    return p


def reference(vermittler_nr: int) -> dict[str, str]:
    rel = hub_rel(vermittler_nr)
    return {"pfad": rel, "uri": obsidian_uri(rel)}


# --------------------------------------------------------------------------- Markdown-Helfer

def _yaml(value: Any) -> str:
    # JSON ist gueltiges YAML (Flow-Stil) -> sicheres Escaping ohne PyYAML.
    if value is None:
        return "null"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return json.dumps(value, ensure_ascii=False)


def render_frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"] + [f"{k}: {_yaml(v)}" for k, v in data.items()] + ["---"]
    return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    data: dict[str, Any] = {}
    for line in text[3:end].strip().splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        try:
            data[key.strip()] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            data[key.strip()] = raw
    body = text[end + 4:].lstrip("\n")
    return data, body


def _replace_frontmatter(text: str, fm: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return fm + text[end + 4:]
    return fm + "\n" + text


def _block(name: str, body: str) -> str:
    return f"<!-- BEGIN:{name} -->\n{body.strip()}\n<!-- END:{name} -->"


def _replace_block(text: str, name: str, body: str) -> str:
    pattern = re.compile(_BLOCK_RE.format(name=re.escape(name)), re.S)
    new = _block(name, body)
    if pattern.search(text):
        return pattern.sub(lambda _: new, text, count=1)
    return text.rstrip() + f"\n\n{new}\n"


def _get_block(text: str, name: str) -> str | None:
    m = re.search(_BLOCK_RE.format(name=re.escape(name)).replace(".*?", "(.*?)"), text, re.S)
    return m.group(1).strip() if m else None


def slugify(text: str, max_len: int = 50) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:max_len].rstrip("-")) or "eintrag"


def _tag(text: str | None) -> str | None:
    return slugify(text, 40) if text else None


def _eur(value: int | None) -> str:
    return f"{(value or 0):,.0f} €".replace(",", ".")


def _cell(value: Any) -> str:
    return "–" if value in (None, "") else str(value).replace("|", "\\|")


# --------------------------------------------------------------------------- Hub-Notiz

def _hub_frontmatter(v: dict[str, Any]) -> str:
    b = v["betreuung"]
    tags = ["vermittler"] + [t for t in (
        f"marktgebiet/{_tag(b['marktgebiet'])}" if b.get("marktgebiet") else None,
        f"status/{_tag(v['status'])}" if v.get("status") else None,
        f"vermittlertyp/{_tag(v['vermittlertyp'])}" if v.get("vermittlertyp") else None,
        f"partner/{_tag(v['status_vertriebspartner'])}" if v.get("status_vertriebspartner") else None,
    ) if t]
    return render_frontmatter({
        "typ": "vermittler-hub",
        "vermittler_nr": v["vermittler_nr"],
        "knr": v["knr"],
        "aliases": [a for a in (v["anzeigename"], v.get("firma_filiale")) if a],
        "name": v["name"],
        "vorname": v["vorname"],
        "firma": v.get("firma_filiale"),
        "vermittlertyp": v.get("vermittlertyp"),
        "status": v.get("status"),
        "status_vertriebspartner": v.get("status_vertriebspartner"),
        "marktgebiet": b.get("marktgebiet"),
        "filiale": b.get("filiale"),
        "betreuer": b.get("name"),
        "tags": tags,
        "db_sync": datetime.now().isoformat(timespec="seconds"),
    })


def _stammdaten_md(v: dict[str, Any]) -> str:
    k, b = v["kontakt"], v["betreuung"]
    rows = [
        ("Vermittler-Nr.", v["vermittler_nr"]), ("KNR", v["knr"]),
        ("Name", v["anzeigename"]), ("Zusatztitel", v.get("sonstiger_titel")),
        ("Anrede", v.get("anrede")), ("Geburtstag", v.get("geburtstag")),
        ("Firma", v.get("firma_filiale")), ("Holding", v.get("firma_holding")),
        ("Vermittlertyp", v.get("vermittlertyp")), ("Status", v.get("status")),
        ("Vertriebspartner-Status", v.get("status_vertriebspartner")),
        ("Abrechnungskreis", v.get("abrechnungskreis")),
        ("Interessen", ", ".join(v.get("interessen") or []) or None),
    ]
    kontakt = [
        ("Adressentyp", k.get("adressentyp")),
        ("Anschrift", ", ".join(p for p in (k.get("strasse"), " ".join(
            x for x in (k.get("plz"), k.get("ort")) if x)) if p) or None),
        ("E-Mail", k.get("email")), ("Telefon dienstl.", k.get("telefon_dienst")),
        ("Handy dienstl.", k.get("handy_dienst")), ("Telefon privat", k.get("telefon_privat")),
    ]
    betreuung = [
        ("Betreuer", f"{b.get('name') or '–'} ({b.get('kuerzel') or '–'}, {b.get('mitarbeiter_id') or '–'})"),
        ("Filiale", f"{b.get('filiale') or '–'} (Nr. {b.get('filial_nr') or '–'})"),
        ("Marktgebiet", b.get("marktgebiet")),
        ("Betreuung seit", b.get("seit")), ("Betreuung bis", b.get("bis")),
    ]

    def table(pairs: Iterable[tuple[str, Any]]) -> str:
        return "| Feld | Wert |\n|---|---|\n" + "\n".join(f"| {a} | {_cell(c)} |" for a, c in pairs)

    zahlen = v.get("geschaeftszahlen") or []
    zahlen_md = "| Jahr | Sparte | Volumen | Anzahl Darlehen |\n|---|---|---:|---:|\n" + "\n".join(
        f"| {z['jahr']} | {z['sparte']} | {_eur(z['volumen_eur'])} | {z['anzahl_darlehen']} |" for z in zahlen
    ) if zahlen else "_Keine Geschäftszahlen erfasst._"

    return "\n\n".join([
        "> Automatisch aus der Datenbank synchronisiert – Änderungen bitte über die API vornehmen.",
        "### Person & Firma\n" + table(rows),
        "### Kontakt\n" + table(kontakt),
        "### Betreuung\n" + table(betreuung),
        "### Geschäftszahlen\n" + zahlen_md,
    ])


def _eintraege_md(vermittler_nr: int) -> str:
    entries = list_entries(vermittler_nr)
    if not entries:
        return "_Noch keine Einträge._"
    lines = []
    for e in entries:
        fm = e["frontmatter"]
        label = EINTRAG_TYPEN.get(fm.get("typ", ""), fm.get("typ", "Eintrag"))
        link = e["datei"][:-3]
        lines.append(f"- {fm.get('datum', '?')} · **{label}** · [[{link}|{fm.get('titel', link)}]]")
    return "\n".join(lines)


def sync_hub(v: dict[str, Any]) -> dict[str, str]:
    """Legt die Hub-Notiz an oder aktualisiert deren verwaltete Bereiche."""
    nr = v["vermittler_nr"]
    rel = hub_rel(nr)
    path = abs_path(rel)
    (path.parent / "Eintraege").mkdir(parents=True, exist_ok=True)
    fm = _hub_frontmatter(v)

    if path.exists():
        text = path.read_text(encoding="utf-8")
        text = _replace_frontmatter(text, fm)
        text = _replace_block(text, "stammdaten", _stammdaten_md(v))
        text = _replace_block(text, "eintraege", _eintraege_md(nr))
    else:
        text = "\n".join([
            fm,
            f"# {v['anzeigename']}" + (f" – {v['firma_filiale']}" if v.get("firma_filiale") else ""),
            "",
            "> [!info] Vermittler-Gehirn",
            f"> Zentraler Wissensknoten zu Vermittler {nr}. Bereiche zwischen `BEGIN`/`END`-Markern "
            "werden automatisch vom Backend gepflegt – eigene Gedanken bitte unter **Freie Notizen** ablegen.",
            "",
            "## KI-Zusammenfassung",
            _block("zusammenfassung", "_Noch keine Zusammenfassung vorhanden._"),
            "",
            "## Stammdaten",
            _block("stammdaten", _stammdaten_md(v)),
            "",
            "## Persönliches Profil",
            _block("profil", _profil_link_md(nr)),
            "",
            "## Einträge",
            _block("eintraege", _eintraege_md(nr)),
            "",
            "## Freie Notizen",
            "",
        ])
    if "<!-- BEGIN:profil -->" not in text:
        # Bestehende Hubs (vor Einfuehrung des Profils angelegt): Abschnitt vor "Einträge" einfuegen.
        anker = "## Einträge\n<!-- BEGIN:eintraege -->"
        abschnitt = f"## Persönliches Profil\n{_block('profil', _profil_link_md(nr))}\n\n"
        text = text.replace(anker, abschnitt + anker, 1) if anker in text else text
    text = _replace_block(text, "profil", _profil_link_md(nr))
    path.write_text(text, encoding="utf-8")
    ensure_profil(v)
    return reference(nr)


# --------------------------------------------------------------------------- Persoenliches Profil
#
# Eine Notiz pro Vermittler: Vermittler/VM-<nr>/VM-<nr> Profil.md
# Persoenliche Infos (Familie, Haustiere, Urlaub, Hobbys ...) als Aufzaehlung unter
# Kategorie-Ueberschriften. Die Notiz gehoert dem Menschen: Das Backend haengt nur
# Zeilen an oder entfernt einzelne Zeilen, Bearbeitungen in Obsidian bleiben erhalten.

PROFIL_KATEGORIEN: dict[str, str] = {
    "familie": "Familie",
    "haustiere": "Haustiere",
    "hobbys": "Hobbys & Freizeit",
    "reisen": "Reisen & Urlaub",
    "vorlieben": "Vorlieben & Gesprächsstil",
    "termine": "Wichtige Daten",
    "sonstiges": "Sonstiges",
}

_KATEGORIE_STICHWORTE: dict[str, tuple[str, ...]] = {
    "haustiere": ("hund", "katze", "kater", "pferd", "haustier", "welpe", "papagei", "hamster", "kaninchen"),
    "reisen": ("urlaub", "reise", "verreist", "ferien", "flug", "kreuzfahrt", "mallorca", "italien", "strand"),
    "familie": ("tochter", "sohn", "kinder", "kind ", "ehefrau", "ehemann", "frau ", "mann ", "verheiratet",
                "hochzeit", "enkel", "eltern", "mutter", "vater", "bruder", "schwester", "baby", "familie"),
    "hobbys": ("hobby", "golf", "tennis", "segeln", "laufen", "marathon", "fussball", "fußball", "ski",
               "radfahren", "fahrrad", "angeln", "jagd", "musik", "spielt", "verein", "fan von", "kocht"),
    "termine": ("geburtstag", "jubilaeum", "jubiläum", "jahrestag", "praxisjubil"),
    "vorlieben": ("mag ", "mag keine", "bevorzugt", "lieber", "trinkt", "kaffee", "tee", "duzen", "siezen",
                  "vegetar", "vegan", "anrufen", "per mail", "morgens", "abends", "humor"),
}

_PROFIL_ZEILE_RE = re.compile(r"^- (?P<text>.+?)(?: · (?P<datum>\d{4}-\d{2}-\d{2}))?\s*$")


def profil_rel(vermittler_nr: int) -> str:
    return f"{folder_rel(vermittler_nr)}/{note_name(vermittler_nr)} Profil.md"


def _profil_link_md(vermittler_nr: int) -> str:
    name = f"{note_name(vermittler_nr)} Profil"
    return f"Persönliche Infos für die Gesprächsvorbereitung: [[{name}|Profil öffnen]]\n\n![[{name}]]"


def kategorie_erkennen(text: str) -> str:
    """Einfache Stichwort-Zuordnung, falls der Nutzer keine Kategorie waehlt."""
    t = f" {text.lower()} "
    for kategorie, woerter in _KATEGORIE_STICHWORTE.items():
        if any(w in t for w in woerter):
            return kategorie
    return "sonstiges"


def _kategorie_slug(ueberschrift: str) -> str:
    for slug, label in PROFIL_KATEGORIEN.items():
        if ueberschrift.strip().lower() == label.lower():
            return slug
    return slugify(ueberschrift, 40)


def _fakt_id(kategorie: str, text: str) -> str:
    import hashlib
    return hashlib.sha1(f"{kategorie}|{text}".encode("utf-8")).hexdigest()[:12]


def ensure_profil(v: dict[str, Any]) -> str:
    """Legt die Profil-Notiz an, falls sie fehlt. Bestehende Notizen werden nie ueberschrieben."""
    nr = v["vermittler_nr"]
    rel = profil_rel(nr)
    path = abs_path(rel)
    if path.exists():
        return rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = render_frontmatter({
        "typ": "vermittler-profil",
        "vermittler_nr": nr,
        "vermittler": f"[[{note_name(nr)}]]",
        "tags": ["vermittler-profil"],
        "erstellt_am": datetime.now().isoformat(timespec="seconds"),
    })
    parts = [fm, f"# Persönliches Profil – {v['anzeigename']}", "",
             "> [!tip] Für die Gesprächsvorbereitung",
             "> Persönliches, das im Gespräch hilft (Familie, Haustiere, Urlaub, Hobbys …). "
             "Eine Info pro Zeile als `- Text · JJJJ-MM-TT`. Darf frei in Obsidian bearbeitet werden.", ""]
    for label in PROFIL_KATEGORIEN.values():
        parts += [f"## {label}", ""]
    path.write_text("\n".join(parts), encoding="utf-8")
    return rel


def read_profil(vermittler_nr: int) -> dict[str, Any]:
    """Liest die Profil-Notiz: Fakten je Kategorie (auch von Hand in Obsidian ergaenzte)."""
    rel = profil_rel(vermittler_nr)
    path = abs_path(rel)
    fakten: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    _, body = parse_frontmatter(text)
    kategorie: str | None = None
    for zeile in body.splitlines():
        if zeile.startswith("## "):
            kategorie = _kategorie_slug(zeile[3:])
            continue
        m = _PROFIL_ZEILE_RE.match(zeile.rstrip())
        if kategorie is None or not m:
            continue
        inhalt = m.group("text").strip()
        if not inhalt:
            continue
        fakten.append({
            "id": _fakt_id(kategorie, inhalt),
            "kategorie": kategorie,
            "kategorie_label": PROFIL_KATEGORIEN.get(kategorie, kategorie),
            "text": inhalt,
            "datum": m.group("datum"),
        })
    return {"pfad": rel, "uri": obsidian_uri(rel), "vorhanden": path.exists(), "fakten": fakten,
            "kategorien": PROFIL_KATEGORIEN}


def add_profil_fakt(v: dict[str, Any], text: str, kategorie: str | None = None,
                    datum: date | None = None) -> dict[str, Any]:
    """Haengt eine persoenliche Info unter der passenden Kategorie-Ueberschrift an."""
    nr = v["vermittler_nr"]
    ensure_profil(v)
    path = abs_path(profil_rel(nr))
    text = " ".join(text.split())  # eine Zeile, keine Markdown-Struktur einschleusen
    kategorie = kategorie or kategorie_erkennen(text)
    label = PROFIL_KATEGORIEN.get(kategorie, PROFIL_KATEGORIEN["sonstiges"])
    kategorie = _kategorie_slug(label)
    zeile = f"- {text} · {(datum or date.today()).isoformat()}"

    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, z in enumerate(lines) if z.startswith("## ") and _kategorie_slug(z[3:]) == kategorie)
    except StopIteration:
        lines += ["", f"## {label}", ""]
        start = len(lines) - 2
    ende = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    letzte = max((i for i in range(start + 1, ende) if lines[i].startswith("- ")), default=start)
    lines.insert(letzte + 1, zeile)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return next(f for f in reversed(read_profil(nr)["fakten"]) if f["text"] == text and f["kategorie"] == kategorie)


def delete_profil_fakt(vermittler_nr: int, fakt_id: str) -> bool:
    path = abs_path(profil_rel(vermittler_nr))
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    kategorie: str | None = None
    for i, zeile in enumerate(lines):
        if zeile.startswith("## "):
            kategorie = _kategorie_slug(zeile[3:])
            continue
        m = _PROFIL_ZEILE_RE.match(zeile.rstrip())
        if kategorie and m and _fakt_id(kategorie, m.group("text").strip()) == fakt_id:
            del lines[i]
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            return True
    return False


def profil_as_text(profil: dict[str, Any]) -> str:
    if not profil["fakten"]:
        return "Keine persönlichen Infos hinterlegt."
    return "\n".join(f"- [{f['kategorie_label']}] {f['text']}" + (f" (notiert {f['datum']})" if f["datum"] else "")
                     for f in profil["fakten"])


# --------------------------------------------------------------------------- Eintraege

def _unique_path(folder: Path, stem: str) -> Path:
    p = folder / f"{stem}.md"
    i = 2
    while p.exists():
        p = folder / f"{stem}-{i}.md"
        i += 1
    return p


def add_entry(v: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Schreibt einen neuen Eintrag (Gespraechsprotokoll, Notiz, ...) als eigene Notiz und verlinkt ihn im Hub."""
    nr = v["vermittler_nr"]
    hub = abs_path(hub_rel(nr))
    if not hub.exists():
        sync_hub(v)

    now = datetime.now()
    datum: date = entry.get("datum") or now.date()
    typ = entry["typ"]
    titel = entry["titel"].strip()
    folder = hub.parent / "Eintraege"
    folder.mkdir(parents=True, exist_ok=True)
    path = _unique_path(folder, f"{datum.isoformat()}_{now:%H%M%S}_{typ}_{slugify(titel)}")
    rel = path.relative_to(Path(settings.vault_path).resolve()).as_posix()

    teilnehmer = entry.get("teilnehmer") or []
    massnahmen = entry.get("massnahmen") or []
    tags = ["vermittler-eintrag", f"typ/{typ}"] + [slugify(t, 40) for t in entry.get("tags") or []]

    fm = render_frontmatter({
        "typ": typ,
        "titel": titel,
        "datum": datum.isoformat(),
        "vermittler_nr": nr,
        "vermittler": f"[[{note_name(nr)}]]",
        "teilnehmer": teilnehmer,
        "autor": entry.get("autor"),
        "quelle": entry.get("quelle"),
        "offene_massnahmen": len(massnahmen),
        "tags": tags,
        "erstellt_am": now.isoformat(timespec="seconds"),
    })
    meta = [f"**Vermittler:** [[{note_name(nr)}|{v['anzeigename']}]]",
            f"**Typ:** {EINTRAG_TYPEN.get(typ, typ)}", f"**Datum:** {datum.isoformat()}"]
    parts = [fm, f"# {titel}", "", " · ".join(meta)]
    if teilnehmer:
        parts.append(f"**Teilnehmer:** {', '.join(teilnehmer)}")
    parts += ["", "## Inhalt", entry["inhalt"].strip()]
    if massnahmen:
        parts += ["", "## Maßnahmen"]
        for m in massnahmen:
            line = f"- [ ] {m['beschreibung'].strip()}"
            if m.get("verantwortlich"):
                line += f" 👤 {m['verantwortlich']}"
            if m.get("faellig_am"):
                line += f" 📅 {m['faellig_am'].isoformat()}"
            parts.append(line)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")

    # Hub-Eintragsliste aktualisieren
    text = hub.read_text(encoding="utf-8")
    hub.write_text(_replace_block(text, "eintraege", _eintraege_md(nr)), encoding="utf-8")

    return {"datei": rel, "uri": obsidian_uri(rel), "datum": datum.isoformat(), "typ": typ, "titel": titel}


def list_entries(vermittler_nr: int) -> list[dict[str, Any]]:
    """Alle Eintrags-Notizen eines Vermittlers, neueste zuerst (auch manuell in Obsidian angelegte)."""
    folder = abs_path(folder_rel(vermittler_nr)) / "Eintraege"
    if not folder.is_dir():
        return []
    vault = Path(settings.vault_path).resolve()
    out = []
    for p in sorted(folder.glob("*.md"), key=lambda x: x.name, reverse=True):
        text = p.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        fm.setdefault("titel", p.stem)
        fm.setdefault("datum", p.name[:10])
        out.append({"datei": p.relative_to(vault).as_posix(), "frontmatter": fm, "inhalt": body})
    return out


# --------------------------------------------------------------------------- Lesen / Zusammenfassen

def read_brain(vermittler_nr: int, limit: int | None = None, seit: date | None = None) -> dict[str, Any]:
    hub = abs_path(hub_rel(vermittler_nr))
    hub_text = hub.read_text(encoding="utf-8") if hub.exists() else ""
    entries = list_entries(vermittler_nr)
    if seit:
        entries = [e for e in entries if str(e["frontmatter"].get("datum", "")) >= seit.isoformat()]
    if limit:
        entries = entries[:limit]
    return {
        "hub": {"datei": hub_rel(vermittler_nr), "inhalt": hub_text},
        "zusammenfassung": _get_block(hub_text, "zusammenfassung") if hub_text else None,
        "profil": read_profil(vermittler_nr),
        "eintraege": entries,
    }


def brain_as_text(brain: dict[str, Any]) -> str:
    """Konkateniert Hub + Profil + Eintraege zu einem LLM-freundlichen Kontextdokument."""
    parts = [f"=== HUB: {brain['hub']['datei']} ===", brain["hub"]["inhalt"]]
    if brain.get("profil"):
        parts += [f"\n=== PERSOENLICHES PROFIL: {brain['profil']['pfad']} ===", profil_as_text(brain["profil"])]
    for e in brain["eintraege"]:
        parts += [f"\n=== EINTRAG: {e['datei']} ===", e["inhalt"]]
    return "\n".join(parts)


def set_summary(vermittler_nr: int, text: str, quelle: str | None = None) -> None:
    hub = abs_path(hub_rel(vermittler_nr))
    if not hub.exists():
        raise FileNotFoundError(hub_rel(vermittler_nr))
    stand = f"_Stand: {datetime.now():%Y-%m-%d %H:%M}" + (f" · Quelle: {quelle}" if quelle else "") + "_"
    content = hub.read_text(encoding="utf-8")
    hub.write_text(_replace_block(content, "zusammenfassung", f"{text.strip()}\n\n{stand}"), encoding="utf-8")


def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Einfache Volltextsuche ueber alle Vermittler-Notizen (Vorstufe zur Vektorsuche)."""
    root = abs_path("Vermittler")
    if not root.is_dir():
        return []
    vault = Path(settings.vault_path).resolve()
    q = query.lower()
    hits: list[dict[str, Any]] = []
    for p in root.rglob("*.md"):
        text = p.read_text(encoding="utf-8")
        idx = text.lower().find(q)
        if idx == -1:
            continue
        m = re.match(r"VM-(\d+)", p.relative_to(root).parts[0])
        start, end = max(0, idx - 120), min(len(text), idx + len(query) + 120)
        hits.append({
            "vermittler_nr": int(m.group(1)) if m else None,
            "datei": p.relative_to(vault).as_posix(),
            "ist_hub": p.parent.name != "Eintraege",
            "ausschnitt": text[start:end].replace("\n", " "),
        })
    # Eintraege vor Hub-Treffern, damit Gespraechsinhalte nicht von Stammdaten verdraengt werden
    hits.sort(key=lambda h: h["datei"], reverse=True)
    hits.sort(key=lambda h: h["ist_hub"])
    return hits[:limit]


# --------------------------------------------------------------------------- Netz (Graph-Ansicht)

_WIKILINK_RE = re.compile(r"!?\[\[([^\]|#^]+)")


def _wikilinks(text: str) -> set[str]:
    return {m.group(1).strip() for m in _WIKILINK_RE.finditer(text)}


def netz(v: dict[str, Any], max_eintraege: int = 15, max_fakten: int = 15) -> dict[str, Any]:
    """Lokaler Graph um einen Vermittler – wie die lokale Graph-Ansicht in Obsidian.

    Knoten: Hub, Profil + persoenliche Infos, Eintraege, Betreuer/Filiale (aus der DB) sowie
    Notizen, die per [[Wikilink]] verlinkt sind oder auf den Vermittler verlinken (Backlinks).
    """
    nr = v["vermittler_nr"]
    name = note_name(nr)
    vault = Path(settings.vault_path).resolve()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def node(nid: str, label: str, typ: str, rel: str | None = None, detail: str | None = None) -> str:
        nodes.setdefault(nid, {"id": nid, "label": label, "typ": typ,
                               "uri": obsidian_uri(rel) if rel else None, "detail": detail})
        return nid

    def edge(a: str, b: str) -> None:
        if a != b and {"von": a, "nach": b} not in edges and {"von": b, "nach": a} not in edges:
            edges.append({"von": a, "nach": b})

    hub = node(name, v["anzeigename"], "vermittler", hub_rel(nr), v.get("firma_filiale"))

    profil = read_profil(nr)
    pid = node(f"{name} Profil", "Persönliches Profil", "profil", profil["pfad"], f"{len(profil['fakten'])} Infos")
    edge(hub, pid)
    for f in profil["fakten"][:max_fakten]:
        edge(pid, node(f"fakt:{f['id']}", f["text"], "fakt", None, f["kategorie_label"]))

    eigene_texte: list[str] = []
    for e in list_entries(nr)[:max_eintraege]:
        fm = e["frontmatter"]
        stem = Path(e["datei"]).stem
        label = EINTRAG_TYPEN.get(str(fm.get("typ", "")), "Eintrag")
        edge(hub, node(stem, str(fm.get("titel", stem)), "eintrag", e["datei"], f"{label} · {fm.get('datum', '')}"))
        eigene_texte.append(e["inhalt"])

    b = v.get("betreuung") or {}
    if b.get("name"):
        edge(hub, node(f"betreuer:{b.get('mitarbeiter_id')}", b["name"], "betreuer", None, "Betreuer"))
    if b.get("filiale"):
        fid = node(f"filiale:{b.get('filial_nr')}", b["filiale"], "filiale", None,
                   f"Filiale · {b.get('marktgebiet') or ''}".strip(" ·"))
        edge(hub, fid)
        if b.get("name"):
            edge(f"betreuer:{b.get('mitarbeiter_id')}", fid)

    # Wikilinks aus eigenen Notizen und Backlinks aus dem restlichen Vault
    hub_path, profil_path = abs_path(hub_rel(nr)), abs_path(profil_rel(nr))
    for p in (hub_path, profil_path):
        if p.exists():
            eigene_texte.append(p.read_text(encoding="utf-8"))
    ausgehend = set().union(*(_wikilinks(t) for t in eigene_texte)) if eigene_texte else set()
    eigener_ordner = abs_path(folder_rel(nr))
    dateien = {p.stem: p for p in vault.rglob("*.md") if ".obsidian" not in p.parts and ".trash" not in p.parts}
    for stem, p in dateien.items():
        if eigener_ordner in p.parents:
            continue
        rel = p.relative_to(vault).as_posix()
        typ = "vermittler-link" if re.fullmatch(r"VM-\d+", stem) else "notiz"
        if stem in ausgehend or Path(stem).name in {Path(a).name for a in ausgehend}:
            edge(hub, node(stem, stem, typ, rel, "verlinkt"))
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if f"[[{name}" in text:
            # Backlink: Eintraege anderer Vermittler zeigen auf deren Hub
            m = re.match(r"Vermittler/(VM-\d+)/", rel)
            if m and m.group(1) != stem:
                edge(hub, node(m.group(1), m.group(1), "vermittler-link", f"Vermittler/{m.group(1)}/{m.group(1)}.md",
                               "erwähnt diesen Vermittler"))
            else:
                edge(hub, node(stem, stem, typ, rel, "verlinkt hierher"))

    return {"zentrum": hub, "knoten": list(nodes.values()), "kanten": edges}
