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
  "auth": {"write_gate": true, "kdf": "pbkdf2-sha256", "iterations": 600000}
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
      "created": "2026-10-10T12:00:00Z",
      "github_id": null,
      "auth": {"kdf": "pbkdf2-sha256", "iterations": 600000, "salt": "<64 hex>", "hash": "<64 hex>"}
    }
  }
}
```

- Handle: `^[a-z][a-z0-9-]{1,31}$` (kleine Buchstaben, Ziffern, Bindestrich; beginnt mit Buchstabe).
- `role` ist genau eines von: `owner`, `maintainer`, `contributor`, `reader` (Reihenfolge = absteigende Berechtigung).
- Mindestens ein nicht deaktivierter `owner` muss immer existieren.
- `disabled: true` entzieht alle Rechte (kein Session, keine Aktionen); der Eintrag bleibt als Historie.
- `created` ist der Beitrittszeitpunkt; `github_id` ist optional (positive Zahl) und informativ — die verbindliche Team-Abbildung liegt in `schema/team.json` unter `github_ids`.
- `auth` ist optional bei reinen Lese-Mitgliedern; fehlt es, kann keine Session erstellt werden. Bei vorhandenem `auth` prüft das Lint `kdf` (`pbkdf2-sha256`), Salt/Hash (je 64 hex) und `iterations` (>= 100 000).
- Im Klartext kommt eine Passphrase nie in diese Datei, in Pläne, Events oder Berichte.

## `schema/team.json` (nur im Teammodus)

```json
{
  "format": "collabmd-team/1",
  "provider": "github",
  "repo": "godmodeai/teamraum",
  "branch": "main",
  "enforcement": "trusted-writers-beta",
  "github_ids": {"alice": "1001", "bob": "1002"},
  "setup_at": "2026-10-10T12:00:00Z"
}
```

- `provider`: `github` (privates Repository) oder `local` (lokaler Bare-Remote, z. B. für Luftlücken-Setups).
- `github_ids`: verbindliche Abbildung der aktiven Mitglieder auf stabile numerische IDs; jede aktive Mitgliedschaft muss abgebildet sein (sonst `team_mapping_incomplete`), keine doppelten IDs.
- `enforcement`: aktuell nur `trusted-writers-beta` (siehe [team-mode.md](team-mode.md)).
- Das File entsteht ausschließlich durch `team_git.py setup` und wird wie jede andere Datei über Plan/Apply geschrieben; Läufe lesen es nur.

## `schema/channels.json`

```json
{
  "format": "collabmd/1",
  "channels": {
    "general": {
      "name": "general",
      "title": "Allgemein",
      "type": "public",
      "purpose": "Gemeinsamer Kanal",
      "members": ["alice"],
      "created_by": "alice",
      "created": "2026-10-10T12:00:00Z",
      "archived": false,
      "archived_at": null
    },
    "dm-alice-bob": {
      "name": "dm-alice-bob",
      "title": "Alice ↔ Bob",
      "type": "direct",
      "purpose": "",
      "members": ["alice", "bob"],
      "created_by": "bob",
      "created": "2026-10-10T12:00:00Z",
      "archived": false,
      "archived_at": null
    }
  }
}
```

- Kanal-ID: `^[a-z0-9][a-z0-9-]{1,62}$`.
- `type` ist genau eines von: `public`, `private`, `direct`.
- `direct`-Kanäle haben exakt zwei Mitglieder und die deterministische ID `dm-<handle-a>-<handle-b>` (handles alphabetisch sortiert).
- `name` deckt sich mit der Kanal-ID; `title` ist Pflicht und eindeutig (Case-insensitive).
- `private`-Kanäle: Beitritt nur durch `maintainer` (Aktion `channels.join-private`); der Inhalt ist nur durch den Skill-Ablauf geschützt, nicht durch das Repository (siehe SKILL.md, Grenzen).
- `archived: true` sperrt neue Posts; bestehende bleiben lesbar; dann muss `archived_at` ein gültiger Zeitstempel sein.
- Jeder Kanal hat mindestens ein Mitglied ohne Duplikate; der letzte verbleibende Mitgliedskanal kann nicht verlassen werden (`last_member`).

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
op: 2cdc31ca47d6436bb3bcdd926864322a
actor: alice
created: 2026-10-10T19:45:32Z
---
- post.created channel=general id=2cdc...
```

- Dateiname = Operations-ID des Plans (UUID-4-Hex), Deckblattfeld `op` gleich.
- Der Body ist eine Aufzählung: eine Zeile `- verb k=v …` pro Operation; `verb` leitet sich von der Plan-Aktion ab (z. B. `posts.edit` → `post.edited`).
- Append-only: Ereignisse werden nie geändert oder gelöscht; eine erneut geplante Operation mit gleicher `op` schlägt mit `event_exists` fehl.
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

Menschenlesbares, Append-only-Tagbuch. Die Datei beginnt mit `# Änderungen` und jede Änderung hängt eine Listezeile an:

```markdown
# Änderungen

- 2026-10-10T19:45:32Z alice init
- 2026-10-10T19:50:00Z alice release 0.1.0
```

Zeilenformat: `- <ISO-Zeitstempel> <handle> <aktion> [detail]`.

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
