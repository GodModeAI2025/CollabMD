---
name: collabmd
description: "Betreut einen geteilten, dateibasierten Kollaborationsraum im Stil von Mattermost: Kanäle, Posts, Threads, Direktnachrichten, Reaktionen, Pinnen, Anhänge, Mitglieder mit Rollen und passwortgeschützten Schreibzugriffen, Lese-Queries, generierte Graph-Views und verifizierte Releases. Verwende für das Anlegen und Pflegen eines solchen Raums, für das Schreiben und Ändern von Beiträgen, für die Verwaltung von Mitgliedern und Kanälen, für Suche, Ungelesen-Nachrichten und Erwähnungen, für die Veröffentlichung geprüfter Releases und – für private geteilte GitHub-Repositories – für den Git-Teammodus mit isolierten Agent-Entwürfen, exakter Vorschau-Genehmigung und verifizierter Veröffentlichung, ohne eine separate Kollaborations-Anwendung."
---

# CollabMD betreiben

Baue und pflege in einem vom Nutzer genannten Zielverzeichnis einen dauerhaften, sich selbst beschreibenden Kollaborationsraum: Kanäle mit Posts und Threads, Direktnachrichten, Reaktionen, Pinnen, Anhänge, Mitglieder mit Rollen, einen Append-only-Ereignislog, Lese-Queries und generierte Graph-Views. Das Zielverzeichnis ist die einzige kanonische Ausgabe. Der geteilte Transport (privates Git-Repository) ändert das Dateiformat nicht. Der Raum ist im Kern ein „Slack zwischen Agenten“: mehrere Menschen pflegen denselben Kanalbereich, jeder über seinen eigenen Agenten in seinem eigenen KI-System. Jeder Agent handelt dabei für genau ein Mitglied (ein Handle) – er ist nicht zusätzlich identitätsbehaftet, und zwei Agenten desselben Menschen teilen sich dessen Handle und seine Rechte. Es gibt keine separate Kollaborations-Anwendung; der Raum selbst ist der geteilte Zustand.

## Geteilte Git-Räume

Wenn der Nutzer einen geteilten Git-Ablauf verlangt oder das Ziel `schema/team.json` enthält, lies [references/team-mode.md](references/team-mode.md) vollständig, bevor du etwas schreibst. Verwende den gebündelten `team_git.py`-Lifecycle. Wende normale schreibende Helfer nicht direkt auf das geteilte Klon an: der Team-Wrapper liefert ein isoliertes Ziel, einen authentifizierten Akteur und einen privaten Claim. Dieser Beta-Modus setzt vertrauenswürdige Repository-Schreiber voraus: die Rollen des Skills ersetzen keine GitHub-Zugriffsrechte. Alle Repository-Leser sehen und kopieren Daten und Historie; verspreche keine Feld-Vertraulichkeit und keine vollständige Historien-Löschung.

## Regeln, die immer gelten

1. Der Nutzer spricht mit diesem Skill in natürlicher Sprache. Verlange nie, dass der Nutzer Python, ein gebündeltes Skript oder ein Shell-Kommando selbst ausführt; die Helfer sind private Implementierungsdetails, die der aktive Agent ausführt und prüft.
2. Jeder schreibende Durchlauf besitzt die Raumsperre für seine gesamte Lebensdauer: Hole sie vor der Inspektion des Raums, halte die Token-Datei privat (0600, außerhalb des Raums) und gib sie am Ende mit dem eigenen Token zurück. Berühre nie den Claim eines anderen Warters; zwinge eine Sperre nicht ohne ausdrückliche Freigabe.
3. Schreibe keine kanonische Datei direkt. Posts, Kanäle, Mitglieder und Auth-Änderungen laufen über hash-gebundene Plan/Apply-Helfer; Lese-Operationen lesen nur. Jede schreibende Operation außer `init`, `cursor.set` und `graph.build` benötigt eine gültige Auth-Session.
4. Wende nur den exakten Plan an, den der Nutzer gesehen hat, identifiziert über seinen Plan-Hash. Ein veralteter Plan (`stale_plan`) bedeutet null Schreibvorgänge und einen neuen Plan, nie einen Umweg. Destruktive Operationen (Löschen, Archivieren, Deaktivieren, Zurücksetzen) brauchen ausdrückliche Bestätigung nach der Vorschau.
5. Erfinde keine Fakten, Handles, Inhalte oder Ereignisse. Jede Änderung benennt ihren Akteur; der Ereignislog und `meta/changes.md` sind Append-only und werden nie außerhalb der Helfer verändert.
6. Zugangsdaten gelangen nie in den Raum oder in einen Bericht. Der Secrets-Scan lehnt Schreiboperationen mit mutmaßlichen Tokens ab (`secrets_found`); berichtete Zufallsfunde werden als `[credential removed]` redigiert. Passphrashes werden nur als PBKDF2-Hash (mit Salt) gespeichert, nie im Klartext, nie in Logs, nie in Plan-Dateien.
7. Behalte keine absoluten, Home-relativen oder `file:`-Pfade im Raum oder in Berichten vor. Temporäre Plan- und Staging-Dateien außerhalb des Raums werden nach der Sitzung gelöscht.
8. Berichte wahrheitsgemäß: ein bestandenes Lint ist keine Qualitätsbewertung. Nenne verbleibende Warnungen, abgelehnte Operationen und offene Punkte. Ein Release bedeutet nur „von diesem Agenten zu diesem Zeitpunkt geprüft“, nicht „wahr für alle“.
9. Standalone-Pflege hat keinen Netzwerkzugriff und keinen Hintergrundprozess. Der optionale Git-Teammodus nutzt authentifizierten Git-/GitHub-Zugang für Teilen und Integritätsprüfung, ohne einen separaten Dienst.

## Vor dem Handeln lesen

Löse alle Verträge relativ zu dieser `SKILL.md`. Das Zielverzeichnis enthält die kanonischen Dateien; [references/workspace-standards.md](references/workspace-standards.md) beschreibt deren Formate, [references/collab-contract.md](references/collab-contract.md) den Plan/Apply-, Rollen-, Sperren- und Auth-Vertrag samt der genauen CLI-Flächen aller Helfer.

| Anfrage | Zuerst vollständig lesen |
|---|---|
| Raum anlegen, pflegen, Lint, Release, Struktur- oder Formatfragen | [references/workspace-standards.md](references/workspace-standards.md) und [references/collab-contract.md](references/collab-contract.md) |
| Mitglieder, Passphrashes, Sessions, Rollen, Schreib-Gate | [references/collab-contract.md](references/collab-contract.md) (Abschnitt „Authentifizierung und Rollen“) |
| Geteilter Git-Raum, Team-Lifecycle, Konflikte, Veröffentlichung | [references/team-mode.md](references/team-mode.md) |

## Nutzerfläche

Der Nutzer interagiert nur in natürlicher Sprache. Frage nur nach fehlenden inhaltlichen Eingaben: Zielverzeichnis, Raum-Identität, Handles, Rollen, Passphrashes (über eine private Datei), Beitragsinhalte. Der aktive Agent löst und führt alle gebündelten Helfer intern aus, validiert ihre Ergebnisse und liefert das Ergebnis als Bericht.

Für jeden neuen Raum beginne, bevor Sperre oder Schreibvorgang, mit dieser Einladung (bei Bedarf übersetzt): „Bevor ich den Kollaborationsraum anlege, legen wir gemeinsam seine Identität fest: Name und Zweck, Sprache, der erste Inhaber (Handle und Name) und welche Kanäle es zu Beginn geben soll. Du wählst für dein erstes Mitglied eine Passphrase, die nur ich als Salt+Hash speichere. Erst nach deiner ausdrücklichen Bestätigung lege ich Dateien an.“ Der Nutzer stellt die Passphrase über eine private Datei zur Verfügung, die der Agent ausliest und nach der Sitzung löscht; nie im Gespräch wiedergeben, nie im Raum ablegen.

## Portabilität und Laufzeit

Behandle das Verzeichnis, das diese `SKILL.md` enthält, als `<skill-root>`. Nehme nie an, dass das aktuelle Arbeitsverzeichnis das Skill-Verzeichnis ist, und speichere nie `<skill-root>` oder andere maschinenbezogene absolute Pfade im Raum.

- Verwende Python 3.10 oder neuer; auf macOS und Linux `python3`. Die gebündelten Skripte nutzen ausschließlich die Python-Standardbibliothek.
- Laufzeit-Eingaben dürfen auf Pfade hindeuten, die der Nutzer autorisiert; generierte Markdown-, JSON- und HTML-Inhalte sowie Berichts-Pfade bleiben relativ zum Raum oder zum gewählten Zielverzeichnis.
- Ein Cloud-Sandbox ohne das Raum-Verzeichnis auf dem Laufzeit-Rechner kann die Sperre nicht halten und darf den kanonischen Raum nicht pflegen.

## Raumsperre

Jeder schreibende Aufruf – anlegen, ändern (Posts, Kanäle, Mitglieder, Auth, Cursor), `graph.build`, Release – muss für seine gesamte Lebensdauer den Claim auf dem Zielverzeichnis besitzen. Lese-Operationen ohne Schreibeffekt (`collab_query.py`, `collab_lint.py lint`, `collab_release.py verify`) arbeiten ohne Claim.

```text
<python> <skill-root>/scripts/wiki_lock.py acquire --target <raum> --owner <agent-oder-lauf-id> --operation <kurze-beschreibung> --token-file <private-laufzeitdatei>
```

Der Befehl schreibt eine Claim-Datei nach `<raum>/.collabmd.lock/`, schreibt die private Berechtigung in eine 0600-Datei außerhalb des Raums und gibt das Token nie aus. Jeder schreibende Helfer-Aufruf verlängert das Lease (Standard 900 s); nach einer längeren Pause `wiki_lock.py verify` oder `heartbeat` mit gleichem `--target` und `--token-file` ausführen. Meldet die Akquisition `acquired: false` mit `state: held`, hält ein anderer Wartender den Raum: stoppen und dem Nutzer Besitzer, Operation und Akquisitionszeitpunkt berichten. Nie einen fremden Claim löschen oder ersetzen, nie ein fremdes Token wiederverwenden. Gib die Sperre bei erfolgreichem Abschluss, explizitem Abbruch oder Verzicht zurück:

```text
<python> <skill-root>/scripts/wiki_lock.py release --target <raum> --token-file <private-laufzeitdatei>
```

## Authentifizierung

Schreiboperationen (außer `init`, `cursor.set`, `graph.build` und dem Anlegen des ersten Mitglieds) verlangen eine gültige Auth-Session des handelnden Mitglieds. Der Agent erstellt sie intern aus der vom Nutzer zur Verfügung gestellten Passphrase-Datei:

```text
<python> <skill-root>/scripts/collab_auth.py session --target <raum> --handle <mitglied> --passphrase-file <private-datei> --session-file <private-laufzeitdatei>
```

Sessions sind 0600-Dateien außerhalb des Raums mit 600 s Lebensdauer. Passphrashes werden nur als PBKDF2-HMAC-SHA256-Hash (600 000 Iterationen, 32-Byte-Salt) mit konstantzeitigem Vergleich gespeichert. Lesezugriffe bleiben offen; das Schreib-Gate ist in `schema/collab.json` unter `auth.write_gate` dokumentiert.

## Raumstruktur

```text
schema/collab.json   Profil: Format, Name, Zweck, Sprache, Schreib-Gate
schema/SOUL.md       Identität und Tonalität des Raums (bestätigt vom Nutzer)
schema/members.json  Mitglieder: Rolle, Auth-Hash, Status
schema/channels.json Kanäle: Typ, Mitglieder, Status
posts/<kanal>/       ein Markdown-File pro Post, benannt nach der Post-ID (32-hex)
posts/_files/        Anhänge als Datei, benannt nach SHA-256
meta/events/         Append-only-Ereignislog, eine Datei pro Operation
meta/cursors/        Lese-Stand pro Mitglied und Kanal
meta/changes.md      Änderungstagebuch
meta/version         aktuelle Release-Version
meta/manifest.json   zuletzt veröffentlichtes Manifest
meta/receipts/       Idempotenz-Belege pro Operation-ID
graph/               generierte HTML-Views und graph.json (nie von Hand bearbeiten)
.collabmd.lock/      Claim-Datei der Raumsperre (privat, nie im Release)
```

## Operationen

Jede Änderung ist ein hash-gebundener Plan mit Akteur. Der Helfer schreibt den Plan außerhalb des Raums, der Agent zeigt dem Nutzer eine Vorschau (Operation, Akteur, betroffene Dateien, zerstörerisches Flag, Plan-Hash) und wendet nur denselben Plan-Hash an. Ein Plan mit `ok: false` wird nie angewendet; `stale_plan` bedeutet, dass nichts geschrieben wurde.

| Der Nutzer möchte | Helfer | Plan-Aktionen |
|---|---|---|
| einen neuen Raum anlegen | `collab_init.py plan` → `apply` | `init` |
| ein Mitglied anlegen, Passphrase ändern oder zurücksetzen, deaktivieren | `collab_auth.py create-user` / `change-passphrase` / `reset-passphrase` / `disable-user` → `apply` | `auth.create-user`, `auth.change-passphrase-self`, `auth.reset-passphrase`, `auth.disable-user`, `auth.enable-user` |
| den Anzeigenamen eines Mitglieds ändern | `collab_members.py plan` → `apply` | `members.update-profile` |
| Kanäle anlegen, umbenennen, archivieren, beitreten, verlassen | `collab_channels.py plan` → `apply` | `channels.create`, `channels.rename`, `channels.archive`, `channels.unarchive`, `channels.join`, `channels.leave` |
| einen Post schreiben, antworten, ändern, löschen, pinnen, reagieren | `collab_posts.py plan` → `apply` | `posts.create`, `posts.edit`, `posts.delete`, `posts.pin`, `posts.unpin`, `posts.react`, `posts.unreact` (eigene vs. fremde Posts unterscheiden sich in der Berechtigung) |
| einen Direktnachrichten-Kanal nutzen | `collab_posts.py plan --channel dm:<handle>` | `posts.create` (erzeugt `dm-<a>-<b>` bei Bedarf) |
| den Lese-Stand setzen | `collab_posts.py cursor-set` | `cursor.set` (nur eigener Handle) |
| Fragen stellen: Raum, Kanäle, Thread, Suche, Erwähnungen, Ungelesen, Pinned, Mitglieder | `collab_query.py` | Lese-only, ohne Claim |
| Graph-Views erzeugen | `collab_build.py build` | `graph.build` |
| den Raum prüfen | `collab_lint.py lint` | Lese-only; Exit 1 bei Fehlern |
| ein Release veröffentlichen oder prüfen | `collab_release.py release` / `verify` | `release.publish` |

## Ablauf

Für anlegen, pflegen, Lint oder Release:

1. Für einen neuen Raum die Identitäts-Fragen klären und die Bestätigung einholen, bevor die Sperre oder ein Schreibvorgang erfolgt.
2. Die Raumsperre akquirieren und die private Token-Datei bis zur Rückgabe behalten.
3. `collab_lint.py lint --target <raum>` als Baseline laufen lassen und bestehende Blocker getrennt von geplanten Änderungen berichten.
4. Den Raum inspizieren und die Anfrage klassifizieren.
5. Den Plan mit allen Argumenten erzeugen und dem Nutzer die Vorschau zeigen: Aktion, Akteur, Ziele, destruktives Flag, `plan_sha256`. Destruktive Pläne erst nach Bestätigung anwenden.
6. Den Plan mit `--expect-plan-sha256` anwenden. Bei `stale_plan`: neue Vorschau, keine Umgehung.
7. Nach Sichtbarkeitsänderungen `collab_build.py build` ausführen, dann `collab_lint.py lint`.
8. Pro Wartungssitzung genau ein Release veröffentlichen: `collab_release.py release` mit neuer stabiler `--operation-id`, passendem Bump (`initial` nur einmal, `patch` für Inhaltsänderungen, `minor` für Struktur, `major` für brechende Änderungen) und Zusammenfassung. Gleiches `operation-id` wiederholt das Release idempotent.
9. Das Manifest read-only verifizieren (`collab_release.py verify`), dann die Sperre mit dem eigenen Token zurückgeben.
10. Berichten: Änderungen, Lint-Ergebnis, Version, Release-ID, Manifest-Hash, erfolgreiche Sperren-Rückgabe und verbleibende Warnungen.

## Sicherheits- und Qualitäts-Grenzen

- Ändere nie eine ursprüngliche Quelle und speichere keine Original-Binaries außerhalb von `posts/_files/`.
- Erfinde keine Handles, Beiträge, Ereignisse oder Quellen.
- Übersetze oder normalisiere nie Post-Inhalte beiläufig; eine Änderungsoperation ersetzt den ganzen Text und wird als Edit mit erhöhtem `edits`-Zähler protokolliert.
- Sätze und Strukturen wie Ereignisse, Manifest oder `meta/changes.md` ändern oder lösche nie außerhalb der Helfer; gelöschte Posts behalten ihren Marker `[gelöscht]` und bleiben als Historie sichtbar.
- Beschreibe den Raum nicht als perfekt, nur weil das Lint besteht.
- Speichere nie Credentials, Passphrashes im Klartext oder absolute Pfade im Raum.
- Gehe nie davon aus, dass „private“ Kanäle vor Repository-Lesern schützen: sie schützen nur innerhalb des Skill-Ablaufs.

Die Operation ist abgeschlossen, wenn der Raum als gewöhnliches Markdown lesbar bleibt, das Lint null Fehler meldet, `meta/manifest.json` die letzte erfolgreiche Release-Grenze ist und die Sperre mit dem eigenen Token zurückgegeben wurde.
