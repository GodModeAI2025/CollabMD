# Kollaborations-Vertrag

Dies ist der verbindliche Vertrag zwischen Agent und Raum: Plan/Apply-Mechanik, Berechtigungen, Authentifizierung, Raumsperre, Fehlercodes und die genauen Befehlsflächen aller Helfer. Alle Helfer liegen unter `<skill-root>/scripts/` und akzeptieren `--target <raum>` als Zielpfad.

## Plan/Apply-Mechanik

Jede schreibende Operation folgt demselben Muster:

1. **plan**: Der Helfer validiert den Raum, prüft Berechtigung und Voraussetzungen, bereitet alle neuen Inhalte in einem externen Staging-Verzeichnis (`--content-dir`) vor und schreibt einen hash-gebundenen Plan nach `--output`. Der Plan enthält:
   - `format`: `collabmd/1`
   - `op`: Operations-ID (UUID-4-Hex)
   - `action`: die Plan-Aktion (z. B. `posts.create`)
   - `actor`: das handelnde Mitglied (Handle)
   - `created`: Zeitstempel
   - `preconditions`: `Pfad → SHA-256` (bzw. `null` für „darf nicht existieren“)
   - `ops`: Liste von `{action: create|update|delete, path, ...}`; bei `create`/`update` zwingend `content_file` + `content_sha256` (und bei Binärdaten `binary: true`)
   - `events`: Kurzform-Zeilen für den Ereignislog
   - `destructive`: bool
   - `plan_sha256`: SHA-256 der kanonischen Plan-Inhalte ohne dieses Feld selbst
2. **Vorschau**: Der Agent zeigt dem Nutzer `action`, `actor`, die betroffenen Pfade, `destructive` und `plan_sha256`. Destruktive Pläne (Löschen, Archivieren, Deaktivieren) werden nur nach Bestätigung fortgesetzt.
3. **apply**: Der Helfer prüft in dieser Reihenfolge: Plan-Format → `--expect-plan-sha256` (Konstantezeit-Vergleich) → Claim/Token → Berechtigung → Auth-Session → Preconditions (alle Hashes müssen noch stimmen) → Spiegel-Anwendung: ein kompletter temporärer Spiegel des Raums wird kopiert, alle Ops werden dort ausgeführt, dann wird der Spiegel atomar zurückkopiert. Danach werden Ereignis und `meta/changes.md` (wo vorgesehen) angehängt.

Ein Fehler zu jedem Punkt bedeutet **null Schreibvorgänge im Ziel**. Ein Hash-Mismatch heißt `stale_plan` – nie umgehen, nie neu berechnen und weitermachen.

Pläne liegen außerhalb des Raums und dürfen temporär maschinenbezogene Pfade enthalten (`content_file`); sie werden nach der Sitzung gelöscht.

## Berechtigungen (Rollen)

Rollenreihenfolge (absteigend): `owner` > `maintainer` > `contributor` > `reader`. `disabled` entzieht alle Rechte.

| Aktion | Mindestrolle | Anmerkung |
|---|---|---|
| `posts.create` | `contributor` + Kanal-Mitglied | |
| `posts.edit-self`, `posts.delete-self`, `posts.pin-self`, `posts.unpin-self` | Kanal-Mitglied (eigener Post) | |
| `posts.edit-other`, `posts.delete-other`, `posts.pin-other`, `posts.unpin-other` | `maintainer` | fremde Posts |
| `posts.react`, `posts.unreact` | Kanal-Mitglied | egal, wem der Post gehört |
| `channels.create` | `maintainer` | Akteur wird Mitglied |
| `channels.rename`, `channels.archive`, `channels.unarchive` | `maintainer` | |
| `channels.join` | `contributor` | in `private`-Kanäle zusätzlich: Akteur mindestens `maintainer` (gleiche Aktion) |
| `channels.leave` | Kanal-Mitglied | letztes Mitglied kann nicht verlassen (`last_member`), stattdessen archivieren |
| `members.update-profile` (eigener Name) | eigenes Mitglied | |
| `members.update-profile` (Name eines anderen) | `maintainer` | |
| `auth.create-user` | `maintainer` | beim ersten Mitglied entfällt das Schreib-Gate (Session) |
| `auth.change-passphrase-self` | eigenes Mitglied | |
| `auth.reset-passphrase`, `auth.disable-user`, `auth.enable-user` | `owner` | |
| `graph.build` | aktives Mitglied | |
| `release.publish` | `contributor` | zusätzlich: Sperre, Session, Lint ohne Fehler |
| `init` | — | nur ins leere Ziel, ohne Mitglieder |

## Authentifizierung und Schreib-Gate

- Passphrashes werden mit **PBKDF2-HMAC-SHA256** (600 000 Iterationen, 32-Byte-Salt) zu einem SHA-256-Hash; gespeichert werden `kdf`, `iterations`, `salt` (hex) und `hash` (hex) in `schema/members.json`. Der Vergleich erfolgt konstantzeitig.
- Eine **Session** ist eine 0600-Datei außerhalb des Raums: `{"handle", "created", "expires", "ttl_seconds"}` mit 600 s Lebensdauer. Sie entsteht über `collab_auth.py session` aus der Passphrase-Datei und wird nie in den Raum, in Pläne oder Berichte geschrieben.
- Das **Schreib-Gate** gilt für alle schreibenden Aktionen außer `init`, `cursor.set`, `graph.build` und `auth.create-user` bei leeren `members`. Es prüft: Akteur ist aktives Mitglied → Session-Datei existiert → `session.handle == actor` → nicht abgelaufen.
- **Lesezugriffe** (Queries, Lint, Verify, Build der graph.json ohne Schreibrecht) brauchen keine Session.
- In `schema/collab.json` ist das Gate unter `auth.write_gate` dokumentiert; `false` würde das Gate deaktivieren (nur für Tests/Lokalnutzung gedacht, im geteilten Raum nie setzen).

## Raumsperre

- Akquisition: `wiki_lock.py acquire --target <raum> --owner <id> --operation <beschreibung> --token-file <private>`; optional `--maintainer <slot>` und `--lease-seconds`.
- Claim-Datei: `<raum>/.collabmd.lock/claim.json` (Besitzer, Wartender, Operation, Zeiten, Lease, `token_sha256`).
- Token: 64-hex-Zeichenfolge, liegt **nur** in der 0600-Datei unter `--token-file` (außerhalb des Raums), wird nie ausgegeben. Der Claim speichert nur `token_sha256`.
- Lease: Standard 900 s. Jede schreibende Helfer-Aufruf verlängert sie; `verify`/`heartbeat` mit dem eigenen Token prüfen/verlängern.
- Rückgabe: `wiki_lock.py release --target <raum> --token-file <private>` – nur mit passendem Token, sonst `token_mismatch` und der Claim bleibt stehen.
- Ein zweiter `acquire` meldet `acquired: false`, `state: held` (mit den Claim-Daten). Nie fremde Claims löschen oder ersetzen; nie ein fremdes Token verwenden.

## Fehlercodes

Jeder Helfer gibt strukturiertes JSON auf stdout aus. Bei Erfolg steht `ok: true`; bei einem kontrollierten Fehler steht `ok: false` plus `error` (Code) und `message` (deutsch), und der Exit-Code ist 1. Häufige Codes:

| Code | Bedeutung |
|---|---|
| `not_a_workspace` | Ziel ist kein CollabMD-Raum (fehlendes Profil) |
| `target_not_empty` | Init-Ziel ist nicht leer (ausgenommen `.collabmd.lock`/`.gitkeep`) |
| `stale_plan` | Plan-Hash oder eine Voraussetzung weicht ab – nichts wurde geschrieben |
| `file_exists` / `file_missing` | Create-Ziel existiert / Update-Ziel fehlt |
| `permission_denied` | Akteur fehlt, ist deaktiviert oder die Rolle reicht nicht |
| `auth_required` | Schreib-Gate ohne gültige Session |
| `auth_failed` | Passphrase passt nicht zum gespeicherten Hash |
| `auth_session_mismatch` | Session gehört zu einem anderen Mitglied als dem Akteur |
| `auth_session_expired` | Session-Datei abgelaufen |
| `no_auth` | Mitglied hat keinen Auth-Eintrag (keine Session möglich) |
| `user_exists` / `user_missing` | Handle-Konflikt bzw. unbekanntes Mitglied |
| `secrets_found` | Schreibinhalt enthält mutmaßliche Zugangsdaten |
| `invalid_handle` / `invalid_channel_id` / `invalid_post_id` / `bad_cursor` | Formatfehler in einer Kennung |
| `not_member` / `already_member` / `last_member` | Kanal-Mitgliedschaft (fehlt / bereits da / letztes Mitglied) |
| `channel_missing` / `channel_archived` / `channel_exists` | Kanal unbekannt / gesperrt / ID belegt |
| `post_missing` / `post_deleted` / `post_wrong_channel` | Post unbekannt / gelöscht / falscher Kanal |
| `bad_thread_root` | Antwort auf einen Thread-Post (Schachtel) oder unbekannte Root |
| `bad_dm` / `bad_emoji` / `empty_body` / `empty_query` | DM-Form, Reaktions-Emoji, leeres Post- bzw. Suchfeld |
| `not_self` | Aktion betrifft nicht den eigenen Handle (z. B. Cursor, Passwort) |
| `token_file_exists` / `token_mismatch` / `claim_expired` / `no_claim` | Sperren-Konflikte (`acquire` meldet statt Fehler `state: held`/`expired`) |
| `missing_token` | schreibende Operation ohne Claim |
| `empty_soul` / `missing_soul` / `missing_passphrase` / `passphrase_too_short` | Init-Voraussetzungen |
| `event_exists` | Operation bereits protokolliert (gleiche `op`) |
| `bad_operation_id` | Release-Operation-ID ist keine 32-hex-Zeichenkette |
| `team_not_setup` | `schema/team.json` fehlt |
| `stale_base` | Remote-Basis weicht von der Preview-Basis ab – Publish verweigert (dann `supersede`) |
| `lint_failed` | Lint meldet Fehler – Release verweigert |
| `version_exists` / `missing_version` / `bad_version` | Versionsvoraussetzungen |
| `no_release` | Kein Manifest vorhanden (verify) |

Weitere Team-Modus-Codes (`team_*`, z. B. `team_run_actor_mismatch`, `team_approval_mismatch`, `team_lint_failed`, `team_mapping_incomplete`) sind in [team-mode.md](team-mode.md) erklärt.

## Befehlsflächen

Alle Befehle laufen über `python3 <skill-root>/scripts/<skript> <unterbefehl> …`.

### `wiki_lock.py`

```text
acquire   --target RAUM --owner ID --operation BESCHREIBUNG --token-file DATEI [--maintainer SLOT] [--lease-seconds N]
verify    --target RAUM --token-file DATEI
heartbeat --target RAUM --token-file DATEI [--lease-seconds N]
release   --target RAUM --token-file DATEI
```

### `collab_init.py`

```text
plan  --target RAUM --name NAME --purpose ZWECK --language CODE [--language-label LABEL]
      --soul-file DATEI --owner-handle HANDLE [--owner-name NAME]
      [--passphrase-file DATEI]
      [--channels "id|titel|typ[,…]"] [--members "handle|name|rolle[,…]"] [--write-gate true|false]
      --content-dir VERZ --output PLAN.json
apply --target RAUM --plan-file PLAN.json --expect-plan-sha256 HASH --token-file DATEI
```

Die Anfangs-Kanäle (`--channels`) und Anfangs-Mitglieder (`--members`) nutzen Pipe-Trennung: `id|titel|typ` (Zweck optional) bzw. `handle|name|rolle`. Bei aktivem Schreib-Gate ist `--passphrase-file` Pflicht (mindestens 8 Zeichen); es wird nur der Hash gespeichert. Direktnachrichten-Kanäle entstehen nicht bei der Anlage, sondern über den ersten Post an `dm:<handle>`.

### `collab_auth.py`

```text
create-user      --target RAUM --handle HANDLE --role ROLLE --passphrase-file DATEI --actor AKTEUR
                 --token-file DATEI [--session-file DATEI] --content-dir VERZ --output PLAN.json
change-passphrase --target RAUM --handle HANDLE --passphrase-file DATEI --actor AKTEUR …(gleiche Form)
reset-passphrase --target RAUM --handle HANDLE --passphrase-file DATEI --actor AKTEUR …(gleiche Form)
disable-user     --target RAUM --handle HANDLE --actor AKTEUR …(gleiche Form)
enable-user      --target RAUM --handle HANDLE --actor AKTEUR …(gleiche Form)
verify   --target RAUM --handle HANDLE --passphrase-file DATEI
session  --target RAUM --handle HANDLE --passphrase-file DATEI --session-file DATEI
apply    --target RAUM --handle HANDLE --plan-file PLAN.json --expect-plan-sha256 HASH
         --token-file DATEI [--session-file DATEI]
```

### `collab_members.py`

```text
plan  --target RAUM --handle HANDLE --name ANZEIGENAME --actor AKTEUR --content-dir VERZ --output PLAN.json
apply --target RAUM --handle HANDLE --plan-file PLAN.json --expect-plan-sha256 HASH
      --token-file DATEI [--session-file DATEI]
```

### `collab_channels.py`

```text
plan  --target RAUM --action channels.create|channels.rename|channels.archive|channels.unarchive|channels.join|channels.leave
      create: --id KANAL-ID --title TITEL [--type public|private] [--purpose ZWECK] [--members "h1,h2, …"]
      rename: --id KANAL-ID --title NEUERTITEL
      archive/unarchive: --id KANAL-ID
      join/leave: --id KANAL-ID   (der Akteur tritt bei bzw. zurück)
      --actor AKTEUR --content-dir VERZ --output PLAN.json
apply --target RAUM --plan-file PLAN.json --expect-plan-sha256 HASH --token-file DATEI [--session-file DATEI]
```

### `collab_posts.py`

```text
plan  --target RAUM --op create|reply|edit|delete|pin|unpin|react|unreact
      --channel KANAL-ID [--post POST-ID] [--body-file DATEI] [--files "Pfad[,Pfad]"]
      [--emoji EMOJI] --actor AKTEUR --content-dir VERZ --output PLAN.json
apply --target RAUM --plan-file PLAN.json --expect-plan-sha256 HASH --token-file DATEI [--session-file DATEI]
cursor-set --target RAUM --handle HANDLE --actor AKTEUR --channel KANAL-ID --cursor ISO-ZEIT --token-file DATEI
```

`--channel dm:<handle>` erzeugt bei `create` den Direktnachrichten-Kanal `dm-<a>-<b>` für Akteur und Gegenstelle. `reply`/`edit`/`delete`/`pin`/`unpin`/`react`/`unreact` verlangen `--post`; `react`/`unreact` verlangen `--emoji`; `edit` verlangt `--body-file`; `create` nimmt optional `--files`.

### `collab_query.py` (Lese-only, ohne Claim)

```text
workspace  --target RAUM
channels   --target RAUM [--member HANDLE]
channel    --target RAUM --id KANAL-ID [--limit N] [--after ISO] [--include-deleted]
thread     --target RAUM --channel KANAL-ID --post POST-ID
search     --target RAUM --text TEXTEIL [--channel KANAL-ID] [--limit N]
mentions   --target RAUM --handle HANDLE [--after ISO]
unread     --target RAUM --handle HANDLE
pins       --target RAUM --channel KANAL-ID
members    --target RAUM
```

### `collab_build.py`

```text
build --target RAUM --actor AKTEUR --token-file DATEI
```

Erzeugt `graph/index.html`, `graph/members.html`, je Kanal `graph/channel-<id>.html` und `graph/graph.json`.

### `collab_lint.py`

```text
lint --target RAUM
```

Exit 0 bei null Fehlern, sonst 1; Ergebnis mit `ok`, `errors`, `warnings`, `stats`.

### `collab_release.py`

```text
release --target RAUM --bump initial|patch|minor|major --operation-id 32-HEX
        --summary ZUSAMMENFASSUNG --actor AKTEUR --token-file DATEI
        [--session-file DATEI]
verify  --target RAUM
```

`release` benötigt Sperre und Session, verweigert bei Lint-Fehlern (`lint_failed`) und schreibt `meta/version`, eine `changes.md`-Zeile, `meta/manifest.json` und den Idempotenz-Beleg `meta/receipts/<operation-id>.json`. Kontrollierte Dateien im Manifest: `schema/collab.json`, `schema/SOUL.md`, `schema/members.json`, `schema/channels.json`, `meta/version`, `meta/changes.md` plus sämtliche Dateien unter `schema/`, `posts/` und `meta/events/` (je SHA-256). Cursoren, Belege und `graph/` sind nicht kontrolliert. `verify` arbeitet read-only ohne Sperre und meldet `ok`, `checked`, `missing`, `mismatched` sowie die Versions-Abweichung (`workspace_version`).

### `team_git.py` (Teammodus)

```text
setup     --target RAUM --actor AKTEUR --provider github|local --repo REPO [--branch BRANCHE]
          [--github-id handle=numeric-id,…] --token-file DATEI [--session-file DATEI]
          --content-dir VERZ --output PLAN.json
apply     --target RAUM --plan-file PLAN.json --expect-plan-sha256 HASH
          --token-file DATEI [--session-file DATEI]
seed      --target RAUM --repo LOKALER-BARE-PFAD [--branch BRANCHE] --runtime VERZ
start     --target RAUM --actor AKTEUR --runtime VERZ
preview   --run-id LAUF --actor AKTEUR --target RAUM --runtime VERZ
approve   --run-id LAUF --actor AKTEUR --preview-file DATEI --runtime VERZ
submit    --run-id LAUF --actor AKTEUR --target RAUM --preview-file DATEI
          --approval-file DATEI [--session-file DATEI] --runtime VERZ
publish   --run-id LAUF --actor AKTEUR --target RAUM [--session-file DATEI] --runtime VERZ
sync      --target RAUM --token-file DATEI --runtime VERZ
read      --target RAUM
read-run  --run-id LAUF --runtime VERZ
cancel    --run-id LAUF --actor AKTEUR --runtime VERZ
supersede --run-id LAUF --actor AKTEUR --target RAUM --runtime VERZ
recover   --runtime VERZ
cleanup   --runtime VERZ [--all]
```

Details, Vertrauensmodell und Konfliktregel: [team-mode.md](team-mode.md).

### `team_integrity.py` (serverseitig, Workflow)

```text
check --worktree VERZ --base-sha 40-HEX --pr-body-file DATEI --actor-github-id ID
```

Läuft im Beratung-Workflow auf der PR: Akteurs-Abbildung, Operation-Block, Diff-Pfade, Lint, Secrets-Scan.

### `secret_screen.py` (interne Hilfs-CLI)

```text
scan   --file DATEI
redact --file DATEI --output DATEI
```

Prüft Text auf mutmaßliche Zugangsdaten (GitHub-/OpenAI-/AWS-/Slack-Tokens, Private-Key-Blöcke, `Bearer`-Tokens, `key=…`/`password=…`-Zuweisungen). `scan` meldet Trefferanzahl und Arten, `redact` ersetzt Treffer durch `[credential removed]`. Wird intern von Init, Posts, Lint, Release und dem Team-Workflow aufgerufen; `secrets_found` verweigert Schreiboperationen.

## Idempotenz und Operation-IDs

- Jede schreibende Aktion trägt eine UUID-4 als `op` (Plan) bzw. `--operation-id` (Release).
- Release mit bereits veröffentlichter `operation-id` liefert `already_published` plus Version, ohne neuen Bump.
- Wiederholtes `apply` desselben Plans schlägt mit `stale_plan` fehl (Create- bzw. Update-Voraussetzungen sind verletzt) – Pläne sind einmalig.
