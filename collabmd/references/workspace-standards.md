# Workspace-Standards (Format `collabmd/1`)

Dieses Dokument beschreibt die kanonischen Formate des CollabMD-Raums. Alle Pfade sind relativ zur Raum-Root. Die Helfer erzeugen und prüfen diese Formate; sie werden nie von Hand geändert.

## Verzeichnislayout

```text
schema/
  collab.json      Profil des Raums
  SOUL.md          Identität und Tonalität (bestätigt vom Nutzer)
  members.json     Mitglieder und Auth-Hashes
  channels.json    Kanäle
  team.json        optional: Teammodus-Konfiguration (Format `collabmd-team/1`)
posts/
  <kanal-id>/      eine Datei pro Post: <post-id>.md
  _files/          Anhänge: eine Datei pro SHA-256-Digest
meta/
  events/          Append-only-Ereignisse: <operation-uuid>.md
  cursors/         <handle>.json: Lese-Stand pro Kanal
  changes.md       Änderungstagebuch (Append-only)
  version          aktuelle Release-Version (SemVer)
  manifest.json    Manifest des letzten Releases
  receipts/        <operation-id>.json: Idempotenz-Beleg
graph/             generierte Views (index.html, members.html, channel-*.html, graph.json); nie von Hand bearbeiten
.collabmd.lock/    claim.json der Raumsperre (nur während eines Wartens)
```

Leerhaltung: `posts/`, `posts/_files/`, `meta/events/`, `meta/cursors/`, `meta/receipts/`, `graph/` tragen einen `.gitkeep`, damit leere Verzeisnisse im Git verbleiben.

## `schema/collab.json`

```json
{
  "format": "collabmd/1",
  "name": "Name des Raums",
  "purpose": "Zweck in einem Satz",
  "language": "de",
  "language_label": "Deutsch",
  "created": "2026-10-10T12:00:00Z",
  "auth": {"write_gate": true, "kdf": "pbkdf2-sha256"}
}
```

- `format` muss exakt `collabmd/1` sein; andere Werte sind Lint-Fehler.
- `language` ist ein portabler Sprachcode (z. B. `de`, `en`); `language_label` ein menschenlesbarer Name.
- `auth.write_gate` dokumentiert, ob Schreiboperationen eine Auth-Session erfordern (Standard `true`).
- `auth.kdf` dokumentiert die Hash-Verfahrensweise: PBKDF2-HMAC-SHA256, 600 000 Iterationen, 32-Byte-Salt, SHA256-Hash.

## `schema/members.json`

```json
{
  "format": "collabmd/1",
  "members": {
    "alice": {
      "name": "Anzeige-Name",
      "role": "owner",
      "disabled": false,
      "joined": "2026-10-10T12:00:00Z",
      "auth": {"kdf": "pbkdf2-sha256", "iterations": 600000, "salt": "<64 hex>", "hash": "<64 hex>"}
    }
  }
}
```

- Handle: `^[a-z][a-z0-9-]{1,31}$` (kleine Buchstaben, Ziffern, Bindestrich; beginnt mit Buchstabe).
- `role` ist genau eines von: `owner`, `maintainer`, `contributor`, `reader` (Reihenfolge = absteigende Berechtigung).
- Mindestens ein nicht deaktivierter `owner` muss immer existieren.
- `disabled: true` entzieht alle Rechte (kein Session, keine Aktionen); der Eintrag bleibt als Historie.
- `auth` ist optional bei reinen Lese-Mitgliedern; fehlt es, kann keine Session erstellt werden.
- Im Klartext kommt eine Passphrase nie in diese Datei, in Pläne, Events oder Berichte.

## `schema/channels.json`

```json
{
  "format": "collabmd/1",
  "channels": {
    "general": {
      "title": "Allgemein",
      "type": "public",
      "purpose": "Zweck (optional)",
      "members": ["alice"],
      "archived": false,
      "created": "2026-10-10T12:00:00Z"
    },
    "dm-alice-bob": {
      "title": "Alice ↔ Bob",
      "type": "direct",
      "members": ["alice", "bob"],
      "archived": false,
      "created": "2026-10-10T12:00:00Z"
    }
  }
}
```

- Kanal-ID: `^[a-z0-9][a-z0-9-]{1,62}$`.
- `type` ist genau eines von: `public`, `private`, `direct`.
- `direct`-Kanäle haben exakt zwei Mitglieder und die deterministische ID `dm-<handle-a>-<handle-b>` (handles alphabetisch sortiert).
- `private`-Kanäle: Beitritt nur durch `maintainer`/`owner`; der Inhalt ist nur durch den Skill-Ablauf geschützt, nicht durch das Repository (siehe SKILL.md, Grenzen).
- `archived: true` sperrt neue Posts; bestehende bleiben lesbar.
- Jeder Kanal hat mindestens ein aktives Mitglied; der letzte verbleibende Maintainer kann ihn nicht verlassen.

## Posts (`posts/<kanal-id>/<post-id>.md`)

Ein Post ist eine Markdown-Datei mit JSON-Backtick-Frontmatter zwischen `---`-Zeilen, gefolgt vom Text. Die Datei wird exakt nach der Post-ID benannt.

```markdown
---
type: post
id: 2cdc31ca47d6436bb3bcdd926864322a
channel: general
author: alice
created: 2026-10-10T19:45:32Z
edited: false
edited_at: null
edits: 0
deleted: false
deleted_at: null
pinned: false
thread_root: null
reactions: {"thumbsup": ["bob"]}
files: ["d39967ef..."]
---
Der Post-Text in Markdown.
```

Felder:

| Feld | Typ | Bedeutung |
|---|---|---|
| `type` | string | immer `post` |
| `id` | string | 32-hex, aus der Operation; deckt sich mit dem Dateinamen |
| `channel` | string | Kanal-ID; bei Thread-Antworten der Kanal des Root-Posts |
| `author` | string | Handle des verfassenden Mitglieds |
| `created` | string | ISO-8601-Zeitstempel des Verfassers (UTC, `Z`) |
| `edited` | bool | ob der Post je bearbeitet wurde |
| `edited_at` | string\|null | letzter Bearbeitungszeitpunkt |
| `edits` | int | Anzahl der Bearbeitungsvorgänge (0 bei Neu) |
| `deleted` | bool | Soft-Delete-Flag |
| `deleted_at` | string\|null | Löschzeitpunkt |
| `pinned` | bool | im Kanal angepinnt |
| `thread_root` | string\|null | ID des Root-Posts; `null` bei eigenen Threads/Top-Level |
| `reactions` | object | Emoji → Liste der reagierenden Handles |
| `files` | list[string] | SHA-256-Digests von Dateien in `posts/_files/` |

Regeln:

- **Threads**: Antworten tragen `thread_root: <root-id>`; schachtelte Threads sind nicht erlaubt (die Ziel-ID selbst darf keine `thread_root` haben).
- **Löschen ist ein Soft-Delete**: `deleted: true`, `deleted_at` gesetzt, und der Text wird exakt zum Marker `[gelöscht]` ersetzt. Die Datei bleibt als Historie; der Inhalt ist nicht wiederherstellbar (aus dem Raum, aus dem Git-History kann ein Repo-Besitzer ihn lesen).
- **Bearbeiten** ersetzt den gesamten Text, setzt `edited: true`, `edited_at` und erhöht `edits` um 1.
- **Reaktionen** sind Emoji-Keys (beliebige nicht-leere Zeichenkette) auf Listen aktiver Mitglieder; `unreact` entfernt den eigenen Handle.
- Zeitstempel sind die Uhr des verfassenden Rechner (UTC-Zeichenkette); es gibt keinen zentralen Server.

## Anhänge (`posts/_files/`)

- Eine Datei pro Inhalt, benannt nach dem hexadezimalen SHA-256-Digest (genau 64 Zeichen).
- Identische Inhalte werden nur einmal gespeichert (Content-Addressing).
- Ein Post referenziert Anhänge über `files`; der Lint prüft, dass jede referenzierte Datei existiert und der Hash stimmt.
- Keine weiteren Metadaten im Raum; Name und MIME-Typ bleiben dem Post-Text überlassen.

## Ereignisse (`meta/events/<uuid>.md`)

Jede Anwendung eines Plans schreibt exakt eine Ereignis-Datei, benannt nach der Plan-Operation-ID (UUID-4-Hex ohne Bindestriche).

```markdown
---
type: event
id: <operation-uuid>
action: posts.create
actor: alice
created: 2026-10-10T19:45:32Z
---
post.created channel=general id=2cdc...
```

- Append-only: Ereignisse werden nie geändert oder gelöscht.
- Die Zeile im Body ist die maschinenlesbare Kurzform `verb k=v ...`; `verb` leitet sich von der `action` ab (z. B. `posts.edit` → `post.edited`).
- Ereignisse sind die Audit-Quelle; `meta/changes.md` ist die menschenlesbare Ergänzung.

## Lese-Stände (`meta/cursors/<handle>.json`)

```json
{
  "handle": "alice",
  "channels": {
    "general": {"cursor": "2026-10-10T19:45:32Z", "updated": "2026-10-10T19:46:00Z"},
    "product": {"cursor": "2026-10-10T18:00:00Z", "updated": "2026-10-10T18:00:30Z"}
  }
}
```

- Pro Mitglied eine Datei, pro Kanal ein ISO-Zeitstempel: alles danach gilt als ungelesen.
- `cursor.set` darf nur den eigenen Handle betreffen (Akteur == Handle).
- Cursor setzen ist ein Schreibvorgang mit Sperre, aber ohne Auth-Session (außerhalb des Schreib-Gates).

## `meta/changes.md`

Menschenlesbares, Append-only-Tagbuch. Jede Session-Zusammenfassung (Init, Release, größere Änderungen) hängt eine Zeile an:

```markdown
## 2026-10-10T19:45:32Z — alice — release 0.1.0
Erstes Release: Raum mit 2 Kanälen veröffentlicht.
```

Format ist frei im Body; die Kopfzeile beginnt mit `## <ts> — <handle> — <beschreibung>`.

## Version und Manifest

- `meta/version`: eine Zeile, SemVer (`MAJOR.MINOR.PATCH`), z. B. `0.1.0`.
- `meta/manifest.json` des letzten Releases:

```json
{
  "format": "collabmd/1",
  "release_id": "<operation-id>",
  "operation_id": "<operation-id>",
  "version": "0.1.0",
  "published": "2026-10-10T19:50:00Z",
  "summary": "Kurze Zusammenfassung",
  "files": {"schema/collab.json": "<sha256>", "...": "<sha256>"}
}
```

- `files` enthält die SHA-256-Hashes aller kontrollierten Dateien: `schema/*`, alle `posts/**`, `meta/events/**`, `meta/version`, `meta/changes.md`.
- `verify` vergleicht die aktuellen Hashes mit dem Manifest und meldet fehlende oder veränderte Dateien.
- `meta/receipts/<operation-id>.json` belegt die Idempotenz: wiederholte Releases mit derselben Operation-ID liefern das bereits veröffentlichte Ergebnis, ohne neue Version.

## `graph/` (generiert)

- `index.html`, `members.html`, `channel-<id>.html`, `graph.json` — erzeugt von `collab_build.py build`, nie von Hand bearbeitet.
- `graph.json` ist die maschinenlesbare Übersicht: Raum, Mitglieder, Kanäle, Posts (ID, Kanal, Autor, Erstellt, Thread-Root, Pinnung, Reaktionen, Anhänge, Ungelesen-Zeilen).
- Ein Build ist ein Schreibvorgang mit Sperre und Auth-Session (Aktion `graph.build`), aktualisiert aber keine Inhalte der Quelle.

## Namens- und Inhaltsregeln

- **Pfade**: immer relativ zur Raum-Root, POSIX-Stil, keine `..`, keine absoluten Pfade, keine `file:`-URLs.
- **Zeichen**: Handles, Kanal-IDs, Emojis und Texte sind UTF-8; Frontmatter-Werte sind JSON-Strings (doppelt angeführt).
- **Zeitstempel**: ISO-8601, UTC, Sekundenauflösung, `Z`-Suffix.
- **Secrets**: Der Schreib-Ablauf scannt Post-Texte, SOUL-Änderungen und Anhang-Namen auf mutmaßliche Zugangsdaten (GitHub-/OpenAI-/AWS-/Slack-Tokens, Private Keys, Bearer-Strings). Treffer werden mit `secrets_found` abgelehnt, bevor ein Plan existiert.
- **Größe**: Ein Post-Text sollte handhabbar bleiben (Empfehlung < 100 KB); große Inhalte gehören als Anhang nach `posts/_files/` und werden im Text referenziert.

## Lesezustand und Rechte am Format

Der Lint ist der einzige strenge Validator: er prüft Format-String, Profile, Mitglieder (Rolle, Auth-Form, eindeutige Handles), Kanäle (Typ, Mitglieder, Direct-Form), Posts (ID, Felder, Thread-Bezug, Reaktionen, Anhänge), Ereignisse und den Secrets-Scan. Der Lint repariert nichts; er meldet. `collab_release.py release` läuft den Lint intern und verweigert ein Release bei Fehlern.
