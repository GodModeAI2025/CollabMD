#!/usr/bin/env python3
"""Generate read-only HTML views under graph/ (never a source of truth)."""
import argparse
import json
import sys
from html import escape
import re

import collabmd_common as C

CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;background:#f4f5f7;color:#172b4d}
.container{max-width:960px;margin:0 auto;padding:16px}
a{color:#0052cc;text-decoration:none}
a:hover{text-decoration:underline}
h1{font-size:22px;margin:8px 0}
h2{font-size:17px;margin:16px 0 8px}
.badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;background:#e2e8f0;color:#42526e;margin-left:6px}
.badge.private{background:#ffe8cc;color:#974f0c}
.badge.direct{background:#e6f4ea;color:#006644}
.badge.archived{background:#ffece8;color:#bf2600}
.post{background:#fff;border:1px solid #dfe1e6;border-radius:8px;padding:12px 16px;margin:8px 0}
.post .meta{font-size:12px;color:#6b778c;margin-bottom:6px}
.post .body{white-space:pre-wrap;line-height:1.45}
.post.reply{margin-left:32px;border-left:3px solid #0052cc}
.post.deleted{opacity:.6}
.pinned h3{margin:8px 0;font-size:14px;color:#6b778c}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid #dfe1e6;padding:6px 10px;font-size:14px;text-align:left}
code{background:#f0f1f3;padding:1px 4px;border-radius:3px;font-size:13px}
pre{background:#041527;color:#fff;padding:10px;border-radius:6px;overflow-x:auto}
pre code{background:none;color:inherit;padding:0}
blockquote{border-left:3px solid #dfe1e6;margin:6px 0;padding:2px 12px;color:#42526e}
.footer{font-size:11px;color:#98a1b3;margin:16px 0}
"""


def render_markdown(text):
    lines = text.split("\n")
    out = []
    in_code = False
    in_list = False
    for line in lines:
        if line.startswith("```"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(escape(line))
            continue
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + inline(escape(line[2:])) + "</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("#### "):
            out.append("<h4>" + inline(escape(line[5:])) + "</h4>")
        elif line.startswith("### "):
            out.append("<h3>" + inline(escape(line[4:])) + "</h3>")
        elif line.startswith("## "):
            out.append("<h2>" + inline(escape(line[3:])) + "</h2>")
        elif line.startswith("# "):
            out.append("<h1>" + inline(escape(line[2:])) + "</h1>")
        elif line.startswith("> "):
            out.append("<blockquote>" + inline(escape(line[2:])) + "</blockquote>")
        elif line.strip():
            out.append("<p>" + inline(escape(line)) + "</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def inline(html):
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    html = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", html)
    html = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|[^)]+)\)", r'<a href="\2">\1</a>', html)
    return html


def page(title, body_html):
    return (
        "<!DOCTYPE html>\n<html lang=\"de\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{escape(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f"<div class=\"container\">\n{body_html}\n"
        "<p class=\"footer\">CollabMD - read-only Ansicht, kanonische Quelle ist das Markdown im Arbeitsraum.</p>\n"
        "</div>\n</body>\n</html>\n"
    )


def post_html(meta, body, is_reply=False):
    cls = "post reply" if is_reply else "post"
    if meta.get("deleted"):
        cls += " deleted"
    badges = ""
    if meta.get("edited"):
        badges += "<span class=\"badge\">bearbeitet</span>"
    if meta.get("pinned"):
        badges += "<span class=\"badge\">gepinnt</span>"
    if meta.get("deleted"):
        badges += "<span class=\"badge archived\">gelöscht</span>"
    reactions = meta.get("reactions", {}) or {}
    reaction_html = ""
    for emoji, handles in sorted(reactions.items()):
        reaction_html += f" {escape(emoji)}×{len(handles)}"
    files_html = ""
    for digest in meta.get("files", []) or []:
        if isinstance(digest, str) and len(digest) == 64:
            files_html += f"<p><a href=\"../../../posts/_files/{digest}\">Anhang {digest[:12]}…</a></p>"
    body_html = "<p><em>[gelöscht]</em></p>" if meta.get("deleted") else render_markdown(body)
    return (
        f"<div class=\"{cls}\"><div class=\"meta\">{escape(str(meta.get('author')))} "
        f"· {escape(str(meta.get('created')))}{badges}{reaction_html and ' · ' + reaction_html or ''}</div>\n"
        f"<div class=\"body\">{body_html}</div>{files_html}</div>\n"
    )


def channel_page(ws, channel_id, channel):
    posts = ws.list_posts(channel_id)
    roots = []
    replies = {}
    for _, meta, body in posts:
        if meta.get("thread_root"):
            replies.setdefault(meta["thread_root"], []).append((meta, body))
        else:
            roots.append((meta, body))
    for key in replies:
        replies[key].sort(key=lambda mb: mb[0].get("created") or "")
    pins = [pm for pm in roots if pm[0].get("pinned") and not pm[0].get("deleted")]
    html = [f"<h1>{escape(channel.get('title', channel_id))}"]
    for tag in ("archived", channel.get("type")):
        if tag in ("archived", "private", "direct", "group"):
            html.append(f"<span class=\"badge {tag}\">{tag}</span>")
    html.append("</h1>")
    if channel.get("purpose"):
        html.append(f"<p>{escape(channel['purpose'])}</p>")
    html.append("<p class=\"meta\">Mitglieder: " + escape(", ".join(channel.get("members", []))) + "</p>")
    if pins:
        html.append("<div class=\"pinned\"><h3>Gepinnt</h3>")
        for meta, body in pins:
            html.append(post_html(meta, body))
        html.append("</div>")
    for meta, body in sorted(roots, key=lambda mb: mb[0].get("created") or ""):
        html.append(post_html(meta, body))
        for rmeta, rbody in replies.get(meta.get("id"), []):
            html.append(post_html(rmeta, rbody, is_reply=True))
    html.append(f"<p><a href=\"../../index.html\">← Übersicht</a></p>")
    return page(f"{channel.get('title', channel_id)} – CollabMD", "\n".join(html))


def index_page(ws, profile, channels, members, posts, revision):
    html = [f"<h1>{escape(profile.get('name', 'CollabMD'))}</h1>"]
    if profile.get("purpose"):
        html.append(f"<p>{escape(profile['purpose'])}</p>")
    rev_bits = []
    if revision.get("workspace_version"):
        rev_bits.append(f"Version {escape(revision['workspace_version'])}")
    if revision.get("release_id"):
        rev_bits.append("Release " + escape(str(revision["release_id"])[:8]) + "…")
    if rev_bits:
        html.append("<p class=\"meta\">" + " · ".join(rev_bits) + "</p>")
    html.append("<h2>Kanäle</h2><table><tr><th>Kanal</th><th>Typ</th><th>Mitglieder</th><th>Letzter Post</th></tr>")
    for channel_id, channel in sorted(channels.items()):
        last = None
        for _, meta, _ in posts:
            if meta.get("channel") == channel_id and not meta.get("deleted"):
                last = meta
        badges = f"<span class=\"badge {channel.get('type')}\">{channel.get('type')}</span>"
        if channel.get("archived"):
            badges += "<span class=\"badge archived\">archiviert</span>"
        last_txt = "–"
        if last:
            last_txt = f"{escape(str(last.get('author')))} · {escape(str(last.get('created')))}"
        html.append(
            f"<tr><td><a href=\"channels/{channel_id}/index.html\">{escape(channel.get('title', channel_id))}</a>{badges}</td>"
            f"<td>{escape(str(channel.get('type')))}</td><td>{len(channel.get('members', []))}</td><td>{last_txt}</td></tr>"
        )
    html.append("</table>")
    html.append(f"<p><a href=\"members.html\">Mitglieder ({len(members)})</a> · {len(posts)} Posts</p>")
    return page(f"{profile.get('name', 'CollabMD')} – CollabMD", "\n".join(html))


def members_page(ws, members):
    html = ["<h1>Mitglieder</h1><table><tr><th>Handle</th><th>Name</th><th>Rolle</th><th>Seit</th></tr>"]
    for handle, entry in sorted(members.items()):
        status = "" if not entry.get("disabled") else " <span class=\"badge archived\">deaktiviert</span>"
        html.append(
            f"<tr><td>{escape(handle)}</td><td>{escape(str(entry.get('name', '')))}</td>"
            f"<td>{escape(str(entry.get('role', '')))}{status}</td><td>{escape(str(entry.get('created', '')))}</td></tr>"
        )
    html.append("</table>")
    html.append("<p><a href=\"index.html\">← Übersicht</a></p>")
    return page("Mitglieder – CollabMD", "\n".join(html))


def do_build(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    C.verify_claim(ws, args.token_file)
    profile = ws.profile()
    members = ws.members_doc()["members"]
    channels = ws.channels_doc()["channels"]
    posts = ws.list_posts()
    C.require_permission(ws.members_doc(), args.actor, "graph.build")
    revision = {}
    version_path = ws.meta / "version"
    if version_path.is_file():
        revision["workspace_version"] = version_path.read_text(encoding="utf-8").strip()
    manifest_path = ws.meta / "manifest.json"
    if manifest_path.is_file():
        try:
            revision["release_id"] = C.read_json(manifest_path).get("release_id")
        except C.CollabError:
            pass
    ws.graph.mkdir(parents=True, exist_ok=True)
    C.atomic_write(ws.graph / "index.html", index_page(ws, profile, channels, members, posts, revision))
    C.atomic_write(ws.graph / "members.html", members_page(ws, members))
    for channel_id, channel in channels.items():
        target = ws.graph / "channels" / channel_id / "index.html"
        C.atomic_write(target, channel_page(ws, channel_id, channel))
    graph = {
        "format": C.FORMAT,
        "generated": C.now_iso(),
        "workspace_version": revision.get("workspace_version"),
        "release_id": revision.get("release_id"),
        "counts": {"channels": len(channels), "members": len(members), "posts": len(posts)},
        "channels": sorted(channels),
        "members": sorted(members),
    }
    C.write_json(ws.graph / "graph.json", graph)
    return {"ok": True, "views": len(channels) + 2, "graph_json": "graph/graph.json"}


def main():
    parser = argparse.ArgumentParser(prog="collab_build.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--target", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--token-file", required=True)
    args = parser.parse_args()
    return C.run_main(lambda: do_build(args))


if __name__ == "__main__":
    sys.exit(main())
