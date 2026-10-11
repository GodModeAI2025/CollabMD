# Teammodus (geteilte Git-Räume)

Der Teammodus macht einen CollabMD-Raum zum geteilten Kanalbereich mehrerer Menschen, die jeweils über ihren eigenen Agenten in ihrem eigenen KI-System arbeiten. Der Transport ist ein privates Git-Repository (Standard: GitHub.com), der geteilte Zustand ist die Branch `main`. Es gibt keinen Dienst, keine Anwendung und keinen Daemon: der Agent läuft die Lifecycle-Befehle lokal, das Repository ist der Server.

## Vertrauensmodell: `trusted-writers-beta`

- **Vertrauensgrenze**: Das Modell setzt vertrauenswürdige Repository-Schreiber voraus. Die Skill-Rollen (`owner`/`maintainer`/`contributor`/`reader`) ersetzen **keine** GitHub-Zugriffsrechte, und ein Repo-Schreiber kann das Repository direkt ändern, ohne den Skill-Ablauf zu nehmen.
- **Zwangsgrenze auf GitHub Free**: Private Repositories ohne bezahlten Plan haben keine erzwungenen Branch-Schutzregeln. Deshalb ist der serverseitige Integritäts-Workflow **beratend** (Status-Check auf der PR), und die verbindliche Veröffentlichungsgrenze ist das **client-seitige Publish-Gate**: `publish` verifiziert unmittelbar vor dem Merge, dass die Remote-Basis exakt die Preview-Basis ist (`stale_base` verweigert sonst den Merge), und die exakte Vorschau (Hash) wurde vom Menschen bestätigt.
- **Alle Repository-Leser sehen alles**: Daten und Git-Historie sind für Repo-Leser lesbar. „Private“ Kanäle schützen nur innerhalb des Skill-Ablaufs, und der Inhalt gelöschter Posts bleibt in der Historie lesbar. Keine Feld-Vertraulichkeit, keine vollständige Historien-Löschung.

## Akteure und Identität

- Jeder Mensch führt genau ein Mitglied (Handle) im Raum. Sein Agent handelt als dieses Mitglied; es gibt keine zusätzliche Agent-Identität. Zwei Agenten desselben Menschen teilen sich dessen Handle.
- `schema/team.json` (Format `collabmd-team/1`) hält die Abbildung der aktiven Mitglieder auf stabile numerische GitHub-IDs (`github_ids`), Provider (`github` oder `local`), Repo, Branch und das Enforcement-Level.
- Der Agent ermittelt seine GitHub-ID über `gh api user`. Ein PR wird nur von dem GitHub-Autor akzeptiert, dessen ID auf den deklarierten Akteur abbildet; die serverseitige Prüfung wiederholt das (`team_integrity.py`).

## Setup (einmalig, vom Owner)

1. Der Owner legt den Raum an (`collab_init.py`) und hält die Raumsperre.
2. `team_git.py setup --provider github --repo owner/repo` erzeugt einen Plan, der `schema/team.json` plus einen **Runtime-Snapshot** des Skills nach `.github/collabmd-runtime/` und den Workflow nach `.github/workflows/team-integrity.yml` schreibt. Der Owner wendet den Plan an und pusht das Ergebnis direkt (Bootstrap-Ausnahme des Modell „nur PRs“).
3. Der Workflow läuft auf `pull_request_target` für PRs mit dem Marker `collabmd-op/1`: er prüft Abbildung des PR-Autors, Operation-Block, erlaubte Diff-Pfade, Lint und Secrets-Scan der zugefügten Zeilen. Der Check ist beratend.

## Lauf-Lebenszyklus (pro Agent-Durchgang)

Jeder schreibende Durchgang ist ein **Run** mit isoliertem Staging außerhalb des Zielraums:

```text
start     → kloniert die aktuelle main in ein privates Staging, meldet base_revision
           (der Agent arbeitet ab hier nur gegen das Staging mit den gewöhnlichen
           collab_-Helfern; die Staging-Sperre gehört dem Lauf)
preview   → Lint des Staging, Berechnung des Preview-Hashes über Basis, Akteur,
           Operationen und Datei-Hashes; Vorschau zeigt dem Menschen Hash + Operationen
approve   → der Mensch bestätigt die exakte Vorschau; der Agent hält die Approve-Datei
submit    → Commit + Push einer Draft-Branch collabmd/<run> und PR mit Operation-Block
           (Marker, operation-id, actor, base-revision, preview-sha256);
           Submit und Publish liegen hinter dem Schreib-Gate (Auth-Session des Akteurs)
publish   → client-seitiges Gateway: Remote main muss exakt base_revision sein,
           sonst stale_base; dann Merge (GitHub: squash + Branch-Löschung)
sync      → spiegelt die aktuelle main in den kanonischen Zielraum
```

Dazwischen: `read` (Modus-Info), `read-run` (Zustand eines Laufs), `cancel` (Staging verwerfen, PR/Branch schließen), `recover` (offene Läufe auflisten), `cleanup` (Lauf-Verzeichnisse entfernen; `--all` bei offenen), `seed` (nur lokaler Provider: Bare-Remote aus dem Raum anlegen).

## Konflikte und veraltete Basen

- Zwei Läufe dürfen parallel existieren; jeder sieht den Stand zu seinem `start`.
- Verändert sich `main` nach dem `start` eines Laufs, meldet `submit` oder `publish` **`stale_base`**: nichts wird gemergt.
- Der Eigentümer des Laufs führt `supersede` aus: das Staging wird auf die neue `main` zurückgesetzt (ältere Drafts werden verworfen), der Agent plant seine Operation auf dem neuen Stand neu, und der normale Preview/Approve/Submit/Publish-Ablauf folgt.
- Eine automatische „Merge mit Konfliktlösung“ existiert bewusst nicht: der Mensch entscheidet pro Vorschau.

## Fehlercodes (Teammodus)

| Code | Bedeutung |
|---|---|
| `team_not_setup` / `team_already_setup` | `schema/team.json` fehlt / Teammodus ist bereits eingerichtet |
| `team_config_invalid` | `schema/team.json` ungültig (Format, Provider, Repo, Branch, `github_ids`, Rollen) |
| `team_mapping_required` | Setup: GitHub-ID eines Mitglieds fehlt (`--github-id handle=<id>`) |
| `team_mapping_incomplete` | Ein Mitglied hat keine GitHub-ID (Abbildung unvollständig) |
| `team_remote_invalid` | Lokaler Remote-Pfad ungültig (lokaler Provider) |
| `team_repo_not_found` | Repository nicht erreichbar (GitHub) |
| `team_remote_exists` / `team_remote_empty` | Lokaler Remote existiert bereits und ist nicht leer / hat noch keine Basis (`seed` ausführen) |
| `team_base_invalid` | `base_revision` ist keine 40-hex-SHA |
| `stale_base` | Remote-Basis weicht von der Preview-Basis ab – Publish verweigert, `supersede` erforderlich |
| `team_diff_forbidden` | Lauf-Diff berührt `.git`, `.collabmd.lock/` oder Pfade außerhalb der erlaubten Bereiche |
| `team_lint_failed` | Lint des Staging meldet Fehler – Preview verweigert |
| `team_preview_invalid` | `preview_sha256` fehlt oder ist ungültig |
| `team_approval_invalid` | Approve-Datei ungültig (Format/`approval_id` fehlt oder nicht erteilt) |
| `team_approval_mismatch` | Approve gehört zu einem anderen Preview oder anderen Akteur |
| `team_run_actor_mismatch` | Lauf gehört zu einem anderen Akteur als dem angegebenen |
| `team_run_not_submitted` / `team_run_finished` | Lauf nicht submitted (Publish) bzw. bereits beendet |
| `run_missing` | Lauf unbekannt |
| `team_runtime_missing` | Runtime-Snapshot-Dateien fehlen im Skill (Setup) |
| `team_open_runs` | Offene Läufe vorhanden – `cleanup` braucht `--all` |
| `team_pr_block_missing` | PR-Body enthält keinen Operation-Block bzw. Felder fehlen (serverseitig) |
| `team_pr_actor_mismatch` / `team_pr_base_mismatch` / `team_pr_preview_mismatch` | PR-Akteur, PR-Basis bzw. PR-Preview weichen vom deklarierten Lauf ab (serverseitig) |

## Lokaler Provider (ohne GitHub)

`--provider local` ersetzt GitHub durch einen lokalen Bare-Remote (Pfad) und PRs durch Branches: nützlich für Luftlücken-Setups und für die Regressionstests. Das Publish-Gate (Basis-Prüfung + Merge) bleibt identisch; es gibt keinen serverseitigen Check.

## Grenzen, die der Agent dem Menschen benennen muss

- Der Integritäts-Workflow ist auf Free-Plänen nicht erzwungen; wer Zwang braucht, muss Branch-Protection selbst aktivieren (bezahlter Plan) oder auf einen Self-Hosted-Server wechseln.
- Ein schreibender Repo-Zugriff kann den Raum außerhalb des Skill-Ablaufs ändern; der Skill prüft Integrität pro Lauf, nicht pro Commit.
- Gelöschte Inhalte und alte Versionen bleiben in der Git-Historie; eine Löschung ist nur ein Soft-Delete im Raum.
- Zeitstempel stammen vom Rechner des verfassenden Agents; es gibt keine zentrale Zeit- oder Serverkomponente.
