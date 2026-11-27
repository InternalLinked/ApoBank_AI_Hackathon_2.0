"""Zugriff auf den persistenten Speicher (in AWS: EFS) fuer DB, Obsidian-Vault und Uploads.

Fuer die App ist EFS ein ganz normaler Ordner: In ECS werden zwei Access Points auf
`/app/data` (SQLite + Uploads) und `/app/vault` (Obsidian-Notizen) gemountet. Dieses Modul
prueft, ob die Daten wirklich dort liegen, und erledigt Wartungsaufgaben:

    python -m backend.storage_maintenance status                          # Wo liegen die Daten? EFS? Schreibbar?
    python -m backend.storage_maintenance ecs-config                      # EFS-Teil der Task-Definition als JSON
    python -m backend.storage_maintenance db-pruefen                      # SQLite: Lage, Integritaet, journal_mode
    python -m backend.storage_maintenance aws-pruefen                     # EFS/Access Points/Mount Targets in AWS
    python -m backend.storage_maintenance vault-status                    # Obsidian: Hubs/Eintraege vs. Vermittler in DB
    python -m backend.storage_maintenance vault-sync [--alle]             # Obsidian: fehlende (alle) Hubs aus DB erzeugen
    python -m backend.storage_maintenance sichern                         # DB-Sicherung + Vault-ZIP nach data/sicherungen/
    python -m backend.storage_maintenance sichern --s3 s3://bucket/pfad   # ... und zusaetzlich nach S3 hochladen
    python -m backend.storage_maintenance excel-import [--excel X.xlsx] [--reset]  # vorhandenen Import nutzen

Excel-Import: Den eigentlichen Import macht `backend.import_excel`. Beim Container-Start importiert
`docker-entrypoint.sh` die mitgelieferte Excel (/app/seed/Musterliste_apoBank.xlsx) automatisch, wenn die
DB leer ist – auf dem EFS also genau einmal. `excel-import` hier ist fuer den manuellen Fall (neue Excel,
Neuaufbau) und sichert vorher die DB. In ECS als einmaliger Task mit ueberschriebenem Kommando, z. B.
`["python", "-m", "backend.storage_maintenance", "excel-import"]`.

Wichtig: SQLite auf EFS vertraegt nur EINEN schreibenden Prozess. Der ECS-Service muss deshalb bei
desiredCount=1 bleiben und so deployen, dass alter und neuer Task nicht gleichzeitig schreiben.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import settings

logger = logging.getLogger("apobank.storage_maintenance")

# Dateisystemtypen, die ueber Neustarts/Deploys hinweg erhalten bleiben (EFS = nfs4).
PERSISTENTE_FS_TYPEN = {"nfs", "nfs4", "efs"}
SICHERUNGEN_BEHALTEN = 14


# --------------------------------------------------------------------------- AWS-EFS-Konfiguration
#
# Alles, was man braucht, um Datenbank und Vault an das EFS anzubinden. Die IDs sind keine Geheimnisse,
# koennen aber per Umgebungsvariable ueberschrieben werden (z. B. fuer ein zweites Projekt/Stage).
#
#   EFS fs-0919d7ce63bf5cdbf
#   ├── /apobank/data   ← Access Point fsap-0519812439ed5c594 → Volume "apobank-data"  → /app/data  (SQLite, Uploads)
#   └── /apobank/vault  ← Access Point fsap-0155e59b164f50601 → Volume "apobank-vault" → /app/vault (Obsidian)

@dataclass(frozen=True)
class EfsVolume:
    name: str              # Volume-Name in der ECS-Task-Definition (volumes[].name / mountPoints[].sourceVolume)
    access_point_id: str   # EFS Access Point, legt Wurzelverzeichnis und POSIX-Benutzer fest
    efs_pfad: str          # Verzeichnis im EFS, das der Access Point als "/" zeigt
    container_pfad: str    # Mountpunkt im Container; muss zu APOBANK_DB_PATH / APOBANK_VAULT_PATH passen

    def task_definition_volume(self, file_system_id: str) -> dict[str, Any]:
        return {"name": self.name, "efsVolumeConfiguration": {
            "fileSystemId": file_system_id,
            "rootDirectory": "/",                    # bei Access Points immer "/" – die Wurzel legt der Access Point fest
            "transitEncryption": "ENABLED",          # TLS zwischen Container und EFS
            "authorizationConfig": {"accessPointId": self.access_point_id, "iam": "ENABLED"},  # Task-Rolle pruefen
        }}

    def mount_point(self) -> dict[str, Any]:
        return {"sourceVolume": self.name, "containerPath": self.container_pfad, "readOnly": False}


@dataclass(frozen=True)
class EfsKonfiguration:
    region: str
    konto_id: str
    file_system_id: str
    security_group_id: str     # erlaubt NFS (TCP 2049) nur von der Security Group des ECS-Tasks
    task_role: str             # IAM-Rolle mit elasticfilesystem:ClientMount/ClientWrite ueber die Access Points
    cluster: str
    service: str
    container: str
    daten: EfsVolume
    vault: EfsVolume

    @property
    def volumes(self) -> tuple[EfsVolume, ...]:
        return (self.daten, self.vault)

    @property
    def task_role_arn(self) -> str:
        return f"arn:aws:iam::{self.konto_id}:role/{self.task_role}"

    @property
    def file_system_arn(self) -> str:
        return f"arn:aws:elasticfilesystem:{self.region}:{self.konto_id}:file-system/{self.file_system_id}"

    def ecs_task_definition_teil(self) -> dict[str, Any]:
        """Der EFS-Teil einer Task-Definition: in register-task-definition einsetzen bzw. in der Console abtippen."""
        return {
            "taskRoleArn": self.task_role_arn,
            "volumes": [v.task_definition_volume(self.file_system_id) for v in self.volumes],
            "containerDefinitions": [{"name": self.container, "mountPoints": [v.mount_point() for v in self.volumes]}],
        }


def _env(name: str, standard: str) -> str:
    return os.getenv(name) or standard


EFS = EfsKonfiguration(
    region=_env("AWS_REGION", "us-west-2"),
    konto_id=_env("APOBANK_AWS_KONTO_ID", "580218335461"),
    file_system_id=_env("APOBANK_EFS_ID", "fs-0919d7ce63bf5cdbf"),
    security_group_id=_env("APOBANK_EFS_SECURITY_GROUP", "sg-044633a4484aade49"),
    task_role=_env("APOBANK_ECS_TASK_ROLE", "apobank-ecs-task-role"),
    cluster=_env("APOBANK_ECS_CLUSTER", "apobank-cluster"),
    service=_env("APOBANK_ECS_SERVICE", "apobank-frontend"),
    container=_env("APOBANK_ECS_CONTAINER", "apobank-frontend"),
    daten=EfsVolume(
        name="apobank-data",
        access_point_id=_env("APOBANK_EFS_AP_DATA", "fsap-0519812439ed5c594"),
        efs_pfad="/apobank/data",
        container_pfad="/app/data",
    ),
    vault=EfsVolume(
        name="apobank-vault",
        access_point_id=_env("APOBANK_EFS_AP_VAULT", "fsap-0155e59b164f50601"),
        efs_pfad="/apobank/vault",
        container_pfad="/app/vault",
    ),
)

# Dateiname der SQLite-DB im Daten-Volume (Container: /app/data/apobank.db, EFS: /apobank/data/apobank.db)
DB_DATEINAME = "apobank.db"


# --------------------------------------------------------------------------- SQL-Datenbank auf dem EFS
#
# SQLite auf EFS (NFS) funktioniert, wenn man drei Regeln einhaelt:
#   1. KEIN WAL-Modus – WAL braucht Shared Memory, das ueber NFS nicht zuverlaessig ist. journal_mode=DELETE.
#   2. Nur EIN schreibender Prozess – ECS-Service mit desiredCount=1 und Deployment min 0 % / max 100 %.
#   3. busy_timeout setzen – kurze Sperren (Netzwerk-Latenz) fuehren sonst sofort zu "database is locked".

SQLITE_BUSY_TIMEOUT_MS = 10_000


def db_pfad() -> Path:
    """Pfad der SQLite-Datei laut Konfiguration (APOBANK_DB_PATH); in ECS /app/data/apobank.db auf dem EFS."""
    return Path(settings.db_path)


def db_pfad_ecs() -> Path:
    """Wo die DB im Container liegen MUSS, damit sie auf dem EFS landet."""
    return Path(EFS.daten.container_pfad) / DB_DATEINAME


def sqlite_verbinden(pfad: Path | None = None, readonly: bool = False) -> sqlite3.Connection:
    """SQLite-Verbindung mit EFS-tauglichen Einstellungen (siehe Regeln oben).

    Fuer eigene Skripte/Module gedacht; das Backend nutzt `db.connect()` (gleiche Datei).
    """
    pfad = Path(pfad or db_pfad())
    if readonly:
        conn = sqlite3.connect(f"file:{quote(pfad.resolve().as_posix(), safe='/:')}?mode=ro", uri=True,
                               timeout=SQLITE_BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    else:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(pfad, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = DELETE")
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sqlalchemy_url(pfad: Path | None = None) -> str:
    """URL fuer SQLAlchemy/pandas, z. B. `create_engine(sqlalchemy_url())` → sqlite:////app/data/apobank.db"""
    return f"sqlite:///{Path(pfad or db_pfad()).resolve().as_posix()}"


def db_pruefen(pfad: Path | None = None) -> dict[str, Any]:
    """Liegt die DB richtig, ist sie heil, und ist sie EFS-tauglich konfiguriert?"""
    pfad = Path(pfad or db_pfad())
    ergebnis: dict[str, Any] = {
        "pfad": str(pfad),
        "erwartet_in_ecs": str(db_pfad_ecs()),
        "existiert": pfad.exists(),
        "groesse_bytes": pfad.stat().st_size if pfad.exists() else 0,
        "dateisystem": dateisystem(pfad.parent) if pfad.parent.exists() else None,
    }
    ergebnis["persistent"] = None if ergebnis["dateisystem"] is None else ergebnis["dateisystem"] in PERSISTENTE_FS_TYPEN
    if pfad.exists():
        with closing(sqlite_verbinden(pfad, readonly=True)) as conn:
            ergebnis["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            ergebnis["integritaet"] = conn.execute("PRAGMA quick_check").fetchone()[0]
            ergebnis["tabellen"] = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
        ergebnis["warnungen"] = [w for w in (
            "journal_mode=wal ist auf EFS unsicher – auf DELETE umstellen" if ergebnis["journal_mode"] == "wal" else None,
            "Integritaetspruefung fehlgeschlagen" if ergebnis["integritaet"] != "ok" else None,
            "DB liegt nicht auf persistentem Speicher" if ergebnis["persistent"] is False else None,
        ) if w]
    return ergebnis


def aws_pruefen() -> dict[str, Any]:
    """Gibt es EFS, Access Points und Mount Targets in AWS wie konfiguriert? (braucht AWS-Zugang, z. B. --profile)"""
    import boto3

    efs = boto3.client("efs", region_name=EFS.region)
    fs = efs.describe_file_systems(FileSystemId=EFS.file_system_id)["FileSystems"][0]
    aps = {a["AccessPointId"]: a for a in efs.describe_access_points(FileSystemId=EFS.file_system_id)["AccessPoints"]}
    mts = efs.describe_mount_targets(FileSystemId=EFS.file_system_id)["MountTargets"]
    return {
        "file_system": {"id": fs["FileSystemId"], "status": fs["LifeCycleState"], "verschluesselt": fs["Encrypted"],
                        "groesse_bytes": fs["SizeInBytes"]["Value"]},
        "access_points": {v.name: {
            "id": v.access_point_id,
            "vorhanden": v.access_point_id in aps,
            "pfad": aps.get(v.access_point_id, {}).get("RootDirectory", {}).get("Path"),
            "pfad_wie_erwartet": aps.get(v.access_point_id, {}).get("RootDirectory", {}).get("Path") == v.efs_pfad,
        } for v in EFS.volumes},
        "mount_targets": [{"zone": m["AvailabilityZoneName"], "status": m["LifeCycleState"]} for m in mts],
    }


@dataclass
class OrtStatus:
    name: str
    pfad: str
    existiert: bool
    schreibbar: bool
    dateisystem: str | None      # z. B. "nfs4" (EFS), "overlay" (Container), None (nicht ermittelbar, z. B. Windows)
    persistent: bool | None      # True = EFS/NFS, False = fluechtiger Container-Speicher, None = unbekannt (lokal)
    belegt_bytes: int


def orte() -> dict[str, Path]:
    """Alle Orte, an denen die App Daten ablegt."""
    return {
        "datenbank": Path(settings.db_path).parent,
        "vault": Path(settings.vault_path),
        "uploads": Path(settings.upload_path),
    }


def _mounts() -> list[tuple[str, str]]:
    """(Mountpunkt, Dateisystemtyp) aus /proc/mounts; leer ausserhalb von Linux."""
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    mounts = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 3:
            mounts.append((parts[1].replace("\\040", " "), parts[2]))
    return mounts


def dateisystem(pfad: Path) -> str | None:
    """Typ des Dateisystems, auf dem `pfad` liegt (laengster passender Mountpunkt)."""
    mounts = _mounts()
    if not mounts:
        return None
    ziel = pfad.resolve().as_posix()
    passend = [(mp, typ) for mp, typ in mounts if ziel == mp or ziel.startswith(mp.rstrip("/") + "/")]
    return max(passend, key=lambda m: len(m[0]))[1] if passend else None


def _schreibbar(pfad: Path) -> bool:
    try:
        pfad.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=pfad, prefix=".schreibtest-", delete=True):
            pass
        return True
    except OSError:
        return False


def _groesse(pfad: Path) -> int:
    if pfad.is_file():
        return pfad.stat().st_size
    return sum(f.stat().st_size for f in pfad.rglob("*") if f.is_file()) if pfad.is_dir() else 0


def status() -> list[OrtStatus]:
    """Fuer jeden Datenort: existiert er, ist er schreibbar, liegt er auf persistentem Speicher (EFS)?"""
    ergebnis = []
    for name, pfad in orte().items():
        typ = dateisystem(pfad) if pfad.exists() else None
        ergebnis.append(OrtStatus(
            name=name,
            pfad=str(pfad),
            existiert=pfad.exists(),
            schreibbar=_schreibbar(pfad),
            dateisystem=typ,
            persistent=None if typ is None else typ in PERSISTENTE_FS_TYPEN,
            belegt_bytes=_groesse(pfad),
        ))
    return ergebnis


def ist_persistent() -> bool | None:
    """True, wenn DB und Vault auf EFS liegen; False, wenn mindestens einer im Container liegt; None = unbekannt.

    Bewusst billig (kein Durchzaehlen der Dateien), damit es im Health-Check laufen kann.
    """
    typen = [dateisystem(orte()[name]) for name in ("datenbank", "vault")]
    werte = [None if typ is None else typ in PERSISTENTE_FS_TYPEN for typ in typen]
    if any(w is False for w in werte):
        return False
    return True if all(w is True for w in werte) else None


def pruefe_beim_start() -> None:
    """Beim App-Start ins Log schreiben, wo die Daten liegen. Bricht nur ab, wenn nichts schreibbar ist."""
    for ort in status():
        if not ort.schreibbar:
            raise RuntimeError(f"Speicherort '{ort.name}' ({ort.pfad}) ist nicht schreibbar")
        if ort.persistent is False:
            logger.warning("Speicherort '%s' (%s) liegt auf %s – Daten gehen beim naechsten Deploy verloren. "
                           "In ECS EFS auf /app/data und /app/vault mounten.", ort.name, ort.pfad, ort.dateisystem)
        else:
            logger.info("Speicherort '%s': %s (%s)", ort.name, ort.pfad, ort.dateisystem or "lokal")


# --------------------------------------------------------------------------- Obsidian-Vault (Wissensbasis fuer den Chat)

def vault_status() -> dict[str, Any]:
    """Wie vollstaendig ist der Vault? Hubs/Eintraege auf dem Volume vs. Vermittler in der DB."""
    from . import db, obsidian

    with closing(db.connect(readonly=True)) as conn:
        nrs = [r[0] for r in conn.execute("SELECT vermittler_nr FROM vermittler")]
    wurzel = obsidian.abs_path("Vermittler")
    eintraege = sum(1 for _ in wurzel.glob("VM-*/Eintraege/*.md")) if wurzel.is_dir() else 0
    fehlend = [nr for nr in nrs if not obsidian.abs_path(obsidian.hub_rel(nr)).exists()]
    return {
        "vault": str(settings.vault_path),
        "vermittler_in_db": len(nrs),
        "hubs": len(nrs) - len(fehlend),
        "fehlende_hubs": len(fehlend),
        "eintraege": eintraege,
    }


def vault_aufbauen(nur_fehlende: bool = True) -> dict[str, int]:
    """Hub-Notizen aus der DB erzeugen, damit der Chat (`suche_notizen`) jeden Vermittler findet.

    `nur_fehlende=True` legt nur fehlende Hubs an (schnell, beim App-Start). `False` baut alle neu –
    dabei werden nur die verwalteten Bloecke ersetzt, freie Notizen und Eintraege bleiben erhalten.
    """
    from . import db, obsidian

    erzeugt = 0
    with closing(db.connect(readonly=True)) as conn:  # sync_hub schreibt nur Dateien, nicht in die DB
        nrs = [r[0] for r in conn.execute("SELECT vermittler_nr FROM vermittler ORDER BY 1")]
        for nr in nrs:
            if nur_fehlende and obsidian.abs_path(obsidian.hub_rel(nr)).exists():
                continue
            vermittler = db.get_vermittler_full(conn, nr)
            if vermittler:
                obsidian.sync_hub(vermittler)
                erzeugt += 1
    if erzeugt:
        logger.info("Vault: %d Hub-Notizen erzeugt (%s)", erzeugt, settings.vault_path)
    return {"vermittler": len(nrs), "erzeugt": erzeugt}


# --------------------------------------------------------------------------- Sicherungen

def _zeitstempel() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sicherungsordner() -> Path:
    ordner = Path(settings.db_path).parent / "sicherungen"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def db_sichern(ziel: Path | None = None) -> Path:
    """Konsistente Kopie der SQLite-DB ueber die Backup-API (sicher auch waehrend die App schreibt)."""
    quelle = Path(settings.db_path)
    if not quelle.exists():
        raise FileNotFoundError(f"Keine Datenbank unter {quelle}")
    ziel = ziel or sicherungsordner() / f"apobank-{_zeitstempel()}.db"
    with sqlite3.connect(quelle) as src, sqlite3.connect(ziel) as dst:
        src.backup(dst)
    logger.info("DB gesichert: %s", ziel)
    return ziel


def vault_zip(ziel: Path | None = None) -> Path:
    """Den Obsidian-Vault als ZIP packen, z. B. zum Oeffnen in der Obsidian-App auf dem Laptop."""
    vault = Path(settings.vault_path)
    ziel = ziel or sicherungsordner() / f"vault-{_zeitstempel()}.zip"
    with zipfile.ZipFile(ziel, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for datei in sorted(vault.rglob("*")) if vault.is_dir() else []:
            if datei.is_file():
                zf.write(datei, datei.relative_to(vault).as_posix())
    logger.info("Vault gepackt: %s", ziel)
    return ziel


def alte_sicherungen_loeschen(behalten: int = SICHERUNGEN_BEHALTEN) -> list[Path]:
    """Pro Art (DB/Vault) nur die neuesten `behalten` Sicherungen auf dem EFS lassen."""
    geloescht = []
    for muster in ("apobank-*.db", "vault-*.zip"):
        dateien = sorted(sicherungsordner().glob(muster), reverse=True)
        for alt in dateien[behalten:]:
            alt.unlink(missing_ok=True)
            geloescht.append(alt)
    return geloescht


# --------------------------------------------------------------------------- S3 (Ablage/Austausch)

def _s3_ziel(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Erwarte s3://bucket/pfad, bekommen: {uri}")
    bucket, _, key = uri[5:].partition("/")
    if not bucket:
        raise ValueError(f"Bucket fehlt in {uri}")
    return bucket, key


def _s3():
    import boto3  # erst hier, damit lokale Nutzung ohne AWS-Konfiguration funktioniert

    return boto3.client("s3")


def nach_s3_hochladen(dateien: list[Path], s3_uri: str) -> list[str]:
    """Dateien unter s3://bucket/prefix/ ablegen (serverseitig verschluesselt)."""
    bucket, prefix = _s3_ziel(s3_uri)
    client = _s3()
    ziele = []
    for datei in dateien:
        key = f"{prefix.rstrip('/')}/{datei.name}" if prefix else datei.name
        client.upload_file(str(datei), bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})
        ziele.append(f"s3://{bucket}/{key}")
        logger.info("Hochgeladen: %s", ziele[-1])
    return ziele


def sichern(s3_uri: str | None = None) -> dict[str, Any]:
    """DB-Sicherung + Vault-ZIP auf dem EFS anlegen, optional nach S3 kopieren, Altbestand aufraeumen."""
    dateien = [db_sichern(), vault_zip()]
    hochgeladen = nach_s3_hochladen(dateien, s3_uri) if s3_uri else []
    geloescht = alte_sicherungen_loeschen()
    return {"dateien": [str(d) for d in dateien], "s3": hochgeladen, "geloescht": len(geloescht)}


# --------------------------------------------------------------------------- Excel-Import

def excel_importieren(excel: Path | None = None, reset: bool = False) -> dict[str, Any]:
    """Den vorhandenen Import (`backend.import_excel`) auf die DB im EFS anwenden – mit Sicherung vorher.

    Standard-Excel ist `APOBANK_EXCEL_PATH` (im Image: /app/seed/Musterliste_apoBank.xlsx).
    Ohne `reset` ist der Import idempotent (Upsert): Chats, Eintraege und freie Notizen bleiben.
    `reset=True` loescht die DB komplett (auch Chats und per App angelegte Vermittler!).
    """
    from . import import_excel

    excel = Path(excel or settings.excel_path)
    if not excel.is_file():
        raise FileNotFoundError(f"Excel nicht gefunden: {excel}")
    sicherung = db_sichern() if db_pfad().exists() else None
    ergebnis = import_excel.run(excel, reset=reset)  # erzeugt auch die Obsidian-Hubs im Vault
    return {"excel": str(excel), "sicherung_vorher": str(sicherung) if sicherung else None, **ergebnis}


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="befehl", required=True)
    sub.add_parser("status", help="Speicherorte, Dateisystem und Belegung anzeigen")
    sub.add_parser("ecs-config", help="EFS-Teil der Task-Definition (taskRoleArn, volumes, mountPoints) als JSON")
    sub.add_parser("db-pruefen", help="Lage, Integritaet und EFS-Tauglichkeit der SQLite-DB")
    sub.add_parser("aws-pruefen", help="EFS, Access Points und Mount Targets in AWS abgleichen")
    sub.add_parser("vault-status", help="Hubs/Eintraege im Obsidian-Vault vs. Vermittler in der DB")
    p_vault = sub.add_parser("vault-sync", help="Fehlende Hub-Notizen aus der DB erzeugen")
    p_vault.add_argument("--alle", action="store_true", help="alle Hubs neu aufbauen (freie Notizen bleiben)")
    p_sichern = sub.add_parser("sichern", help="DB + Vault sichern")
    p_sichern.add_argument("--s3", help="zusaetzlich hochladen nach s3://bucket/prefix")
    p_import = sub.add_parser("excel-import", help="Excel ueber backend.import_excel importieren (sichert vorher)")
    p_import.add_argument("--excel", type=Path, default=None, help="Standard: APOBANK_EXCEL_PATH")
    p_import.add_argument("--reset", action="store_true", help="DB vorher komplett loeschen (auch Chats!)")
    args = ap.parse_args(argv)

    if args.befehl == "status":
        ergebnis: Any = {"persistent": ist_persistent(), "orte": [asdict(o) for o in status()]}
    elif args.befehl == "ecs-config":
        ergebnis = EFS.ecs_task_definition_teil()
    elif args.befehl == "db-pruefen":
        ergebnis = db_pruefen()
    elif args.befehl == "aws-pruefen":
        ergebnis = aws_pruefen()
    elif args.befehl == "vault-status":
        ergebnis = vault_status()
    elif args.befehl == "vault-sync":
        ergebnis = vault_aufbauen(nur_fehlende=not args.alle)
    elif args.befehl == "sichern":
        ergebnis = sichern(args.s3)
    else:
        ergebnis = excel_importieren(args.excel, reset=args.reset)
    print(json.dumps(ergebnis, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
