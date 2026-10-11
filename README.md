# CollabMD

Gemeinsamer, dateibasierter Kollaborationsraum als Agent-Skill – ein „Slack zwischen Agenten“. Mehrere Menschen pflegen denselben Kanalbereich in Markdown-Dateien; jeder arbeitet über seinen eigenen Agenten in seinem eigenen KI-System, und der geteilte Zustand liegt in einem privaten Git-Repository. Es gibt keine Kollaborations-Anwendung, keinen Server und keinen Daemon: das Repository ist der Transport, der Agent führt den Ablauf, und der Raum ist die einzige kanonische Ausgabe.

## Was der Raum kann

- **Kanäle und Posts**: öffentliche und private Kanäle, Markdown-Posts, Pinnen.
- **Threads**: Ein-Level-Antworten auf Root-Posts (kein Verschachteln).
- **Direktnachrichten**: `dm-<a>-<b>`-Kanäle entstehen automatisch durch den ersten Post an `dm:<handle>`.
- **Reaktionen**: Emoji-Profil pro Post, wer mit welchem Emoji reagiert hat.
- **Anhänge**: Content-Adressierung per SHA-256 in `posts/_files/`, Referenz im Post.
- **Mitglieder und Rollen**: `owner` > `maintainer` > `contributor` > `reader`; Passphrashes nur als PBKDF2-HMAC-SHA256-Hash (600 000 Iterationen, Salt), Schreib-Gate über 0600-Auth-Sessions mit 600 s Lebensdauer. Lesezugriffe bleiben offen.
- **Lese-Queries**: Raum, Kanäle, Threads, Volltextsuche, Erwähnungen, Ungelesen (pro Mitglied/Cursor), Pinned, Mitglieder – ohne Schreibzugriff.
- **Ereignislog und Änderungstagebuch**: append-only, pro Operation eine Datei, auditierbar.
- **Graph-Views**: generierte statische HTML-Übersicht (`graph/`) plus `graph.json`.
- **Releases**: verifizierte, hash-gebundene Stände mit SemVer, Manifest und Idempotenz-Belegen.
- **Teammodus**: geteilter Raum über privates Git-Repository mit isolierten Agent-Entwürfen, exakter Vorschau-Genehmigung und client-seitigem Publish-Gate (`trusted-writers-beta`, GitHub Free tauglich).

## Wie es arbeitet (invariante)

1. **Natürliche Sprache**: Der Nutzer spricht mit seinem Agenten; der Agent führt die gebündelten Helfer aus. Niemand muss Python ausführen.
2. **Raumsperre**: Jeder schreibende Durchlauf hält den exklusiven Claim auf dem Raum für seine gesamte Lebensdauer (Lease 900 s, Token 0600 außerhalb des Raums).
3. **Plan → Vorschau → Bestätigung → Apply**: Jede Änderung ist ein hash-gebundener Plan. Der Agent zeigt dem Menschen Aktion, Akteur, Ziele, destruktives Flag und `plan_sha256`; nur dieser exakte Hash wird angewendet. Veralteter Plan (`stale_plan`) = null Schreibvorgänge.
4. **Schreib-Gate**: Schreiboperationen (außer `init`, `cursor.set`, `graph.build`) erfordern eine gültige Auth-Session des handelnden Mitglieds.
5. **Secrets-Scan**: Mutmaßliche Zugangsdaten (GitHub-/OpenAI-/AWS-/Slack-Tokens, Private Keys, Bearer-Strings) werden schon im Plan abgelehnt; Credentials gelangen nie in den Raum oder einen Bericht.
6. **Release pro Sitzung**: Nach Rebuild und striktem Lint genau ein Release; `verify` bestätigt das Manifest read-only.

## Schnellstart

Der Raum wird ausschließlich über einen Agenten mit diesem Skill geführt. Typische erste Sätze:

> „Lege unter `~/Raume/team` einen CollabMD-Raum an. Zweck: Team-Koordination. Ich bin `mz`, Inhaber. Erstell zu Beginn die Kanäle `allgemein`, `projekt` und `ideen`.“

Der Agent führt dann (intern, hash-gebunden): Identitäts-Fragen → Bestätigung → `init` → Vorschau → Apply → `graph.build` → `lint` → Release `initial` → Sperren-Rückgabe. Danach:

> „Schreib im Kanal `projekt`: Sprint startet Montag. Pinne den Post.“
> „Was ist in `allgemein` ungelesen für mich?“
> „Erstelle ein Mitglied `jane` als Contributor.“
> „Veröffentliche ein Patch-Release mit der Zusammenfassung …“

Direkte Befehlsfläche (für Entwickler, QA und den Agenten selbst) dokumentiert: [`collabmd/references/collab-contract.md`](collabmd/references/collab-contract.md). Formate: [`collabmd/references/workspace-standards.md`](collabmd/references/workspace-standards.md).

## Teammodus (geteilter Git-Raum)

Wenn der Raum `schema/team.json` enthält, arbeitet jeder Agent über den `team_git.py`-Lifecycle: isoliertes Staging pro Lauf, Preview-Hash, menschliche Bestätigung, PR/Draft-Branch, client-seitiges Publish-Gate (Remote-Basis muss exakt die Preview-Basis sein, sonst `stale_base`), Merge, Sync in den lokalen Raum. Details und das Vertrauensmodell: [`collabmd/references/team-mode.md`](collabmd/references/team-mode.md).

Kurz: **trusted-writers-beta** setzt vertrauenswürdige Repository-Schreiber voraus. Auf GitHub Free ohne erzwungene Branch-Schutzregeln ist der serverseitige Integritäts-Workflow beratend; die verbindliche Grenze ist das Publish-Gate plus die Bestätigung der exakten Vorschau. Alle Repo-Leser sehen Daten und Historie; „private“ Kanäle schützen nur innerhalb des Skill-Ablaufs.

## Qualitätsniveau

- **Striktes Lint**: Validates Profil, Mitglieder, Kanäle, Posts, Threads, Reaktionen, Anhänge, Ereignisse, Cursor, Version/Manifest und Secrets; repariert nichts, meldet; Exit 1 bei Fehlern.
- **Releases**: SemVer-Bump (`initial`/`patch`/`minor`/`major`), Manifest mit SHA-256 aller kontrollierten Dateien, `verify` für Read-only-Prüfung, Idempotenz über Operation-IDs.
- **CI**: `.github/workflows/check.yml` führt bei jedem Push/PR alle Regressionssuiten aus und prüft, dass das committete Skill-Paket zum aktuellen Stand passt (rebuild + SHA-256).
- **Regressionstests**: Offline, synthetische Daten, unter `qa/tests/` (Smoke, Init, Auth, Chats, Threads/DM, Suche/Anhänge, Releases, Team-Contract, Team-Local).
- **Paket**: `tools/package.py` erzeugt ein deterministisches `dist/collabmd.skill` (ZIP) plus `.sha256`.

## Grenzen (bewusst)

- **Kein Echtzeit**: Der Raum ist ein gemeinsamer Zustand, den jeder Agent ausliest; es gibt keine Push-Notifications. „Ungelesen“ basiert auf Cursoren.
- **Keine Daten-Verschlüsselung**: Passphrashes sind gehasht, der Inhalt ist Klartext. Vertraulichkeit kommt aus dem privaten Repository, nicht aus dem Format.
- **Zeitstempel** stammen vom Rechner des verfassenden Agents (UTC-ISO-String); es gibt keine zentrale Zeitquelle.
- **Löschung ist Soft-Delete**: Gelöschte Posts behalten ihren Marker und bleiben (wie alle Änderungen) in der Git-Historie lesbar.
- **Private Kanäle** sind kein Schutz vor Repo-Lesern, nur vor dem Agenten-Ablauf.

## Repository-Layout

```text
collabmd/            der einsetzbare Skill (SKILL.md, scripts/, references/, assets/, LICENSE, NOTICE)
  scripts/           gebündelte Python-Helfer (nur Standardbibliothek)
  references/        Verträge und Formate (collab-contract, workspace-standards, team-mode)
  assets/            serverseitiger Integritäts-Workflow (YAML)
qa/                  Regressionssuiten und Laufzeit-Artefakte (test-wikis/-runtimes, gitignoret)
tools/               check.py (Suite-Runner), package.py (Skill-Paket)
.github/workflows/   check.yml (CI)
```

## Anforderungen

- Python 3.10 oder neuer (Standardbibliothek allein; auf macOS/Linux `python3`).
- `git`; für den GitHub-Teammodus zusätzlich `gh` (authentifiziert, Repo-Zugriff) und ein privates Repository.
- Ein Agent-Skill-Host (Claude Code, Codex o. Ä.), der das Verzeichnis als Skill laden kann.

## Lizenz

Apache License 2.0 – siehe [`LICENSE`](LICENSE). Attribution und verwandte Werke: [`NOTICE`](NOTICE) und [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Struktur und Prinzipien folgen dem Stil von [AI First CRM](https://github.com/GodModeAI2025/AI_first_CRM) (unabhängige Implementierung, Apache-2.0).
