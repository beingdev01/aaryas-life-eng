#!/usr/bin/env python3
"""Lint a proposed Caddy site block for a codescriet.dev subdomain. Pure text check.

It never runs caddy, never edits /etc/caddy/Caddyfile, never restarts anything.
It checks the house rules for subdomain hosting on this VM and, when the block is
clean, prints the exact backup, validate, restart, verify and rollback commands for
the CEO to run.

House rules it enforces:
- exactly one site block, addressed `http://<name>.codescriet.dev` (plain http:
  Cloudflare terminates TLS; :443 on this VM belongs to the ccsu-bypass Xray VPN);
- never the apex https://codescriet.dev (the clubsite alone), never www, one label only;
- reverse_proxy only to 127.0.0.1 or localhost with an explicit port (or, with
  --static, a file_server rooted outside sensitive paths);
- a Strict-Transport-Security header;
- no admin directive or :2019 (the admin API is off), no tls, no bind,
  no file_server over sensitive paths.

Exit codes: 0 clean (warnings allowed unless --strict), 1 error findings,
2 the block file could not be read.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ZONE = "codescriet.dev"
CADDYFILE = "/etc/caddy/Caddyfile"
HSTS_MIN = 15552000           # what every existing subdomain block on this VM sets

# Subdomains that carry services the company must never harm.
PROTECTED = {
    "www": "redirect/alias of the main clubsite",
    "vpn": "ccsu-bypass Xray VPN (vpn.codescriet.dev:443)",
    "api": "club-api (Express + Prisma)",
    "code": "the Code.SCRIET playground",
    "playground-api": "the playground execute-server",
    "company": "the Paperclip dashboard",
    "judge": "the judge service",
}
FORBIDDEN_PORTS = {
    2019: "the Caddy admin API port (admin is off on this VM)",
    22: "SSH",
    80: "Caddy itself (a proxy loop)",
    443: "the Xray VPN listener",
    5432: "PostgreSQL",
    54329: "the local PostgreSQL instance",
}
KNOWN_PORTS = {
    5001: "club-api", 5002: "the playground execute-server", 3100: "the Paperclip dashboard",
    8081: "the MCP HTTP bridge", 11434: "Ollama", 8080: "the xray fallback site",
}
SENSITIVE_EXACT = {"/", "/home", "/home/ubuntu", "/root", "/etc", "/var", "/var/lib", "/tmp",
                   "/home/ubuntu/aaryas-life", "/usr", "/opt", "/srv"}
SENSITIVE_PREFIX = ("/etc/", "/root/", "/var/lib/", "/proc", "/sys", "/dev", "/boot",
                    "/home/ubuntu/aaryas-life/agents", "/home/ubuntu/aaryas-life/state",
                    "/home/ubuntu/aaryas-life/bin", "/home/ubuntu/db-backups",
                    "/home/ubuntu/clubsite-git", "/var/log")
CLUBSITE_TREE = "/home/ubuntu/clubsite"


@dataclass
class Node:
    tokens: list
    line: int
    children: list = field(default_factory=list)
    parent: "Node | None" = None
    is_block: bool = False

    @property
    def name(self) -> str:
        return self.tokens[0] if self.tokens else ""


@dataclass
class Result:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def error(self, line, msg):
        self.errors.append((line, msg))

    def warn(self, line, msg):
        self.warnings.append((line, msg))


class ParseError(ValueError):
    pass


def strip_comment(line: str) -> str:
    out, quote, prev = [], None, " "
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote and prev != "\\":
                quote = None
        elif ch in "\"`":
            quote = ch
            out.append(ch)
        elif ch == "#" and prev.isspace():
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


def split_tokens(line: str, lineno: int) -> list:
    tokens, cur, quote, i = [], [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(line):
                cur.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
        elif ch in "\"`":
            quote = ch
        elif ch.isspace():
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
        i += 1
    if quote:
        raise ParseError(f"line {lineno}: unterminated quote")
    if cur:
        tokens.append("".join(cur))
    return tokens


def parse(text: str) -> list:
    root = Node([], 0, is_block=True)
    stack = [root]
    for lineno, raw in enumerate(text.splitlines(), 1):
        toks = split_tokens(strip_comment(raw), lineno)
        if not toks:
            continue
        if toks == ["}"]:
            if len(stack) == 1:
                raise ParseError(f"line {lineno}: '}}' closes nothing")
            stack.pop()
            continue
        if "}" in toks:
            raise ParseError(f"line {lineno}: put a closing '}}' on its own line")
        if toks[-1] == "{":
            node = Node(toks[:-1], lineno, parent=stack[-1], is_block=True)
            stack[-1].children.append(node)
            stack.append(node)
        else:
            node = Node(toks, lineno, parent=stack[-1])
            stack[-1].children.append(node)
    if len(stack) != 1:
        raise ParseError(f"block opened on line {stack[-1].line} is never closed")
    return root.children


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.children)


ADDR_RE = re.compile(r"^(?P<scheme>[a-zA-Z][\w+.-]*://)?(?P<host>[^:/]*)(?::(?P<port>\d+))?(?P<path>/.*)?$")
LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
UPSTREAM_RE = re.compile(r"^(?:(?P<scheme>[a-z0-9]+)://)?(?P<host>[^:/]+)(?::(?P<port>\d+))?/?$")


def check_address(site: Node, res: Result, opts) -> list:
    raw = " ".join(site.tokens).replace(",", " ").split()
    labels = []
    if not raw:
        res.error(site.line, "a global options block '{ ... }' is not a site block; "
                  "submit only the one site block")
        return labels
    if raw[0].startswith("("):
        res.error(site.line, "snippets '(name)' are not allowed; submit a plain site block")
        return labels
    for addr in raw:
        m = ADDR_RE.match(addr)
        if not m:
            res.error(site.line, f"cannot read site address {addr!r}")
            continue
        scheme, host = (m.group("scheme") or "").lower(), m.group("host").lower()
        if scheme != "http://":
            res.error(site.line, f"address {addr!r} must start with http:// - Cloudflare "
                      "terminates TLS and :443 on this VM belongs to the ccsu-bypass VPN; "
                      "an https:// or bare address makes Caddy try to take :443 and fetch "
                      "certificates")
        if m.group("port"):
            res.error(site.line, f"address {addr!r} carries a port; Caddy serves subdomains "
                      "on :80 behind Cloudflare only")
        if m.group("path"):
            res.error(site.line, f"address {addr!r} carries a path; one site block per hostname")
        if host == ZONE:
            res.error(site.line, f"{host} is the main domain: https://codescriet.dev is the "
                      "clubsite alone and is never used for hosting")
            continue
        if host == f"www.{ZONE}":
            res.error(site.line, "www.codescriet.dev belongs to the main clubsite; never host on it")
            continue
        if not host.endswith("." + ZONE):
            res.error(site.line, f"{host!r} is not a subdomain of {ZONE}")
            continue
        label = host[: -len(ZONE) - 1]
        if "*" in label:
            res.error(site.line, "wildcard hosts are not allowed; name one subdomain")
            continue
        if "." in label:
            res.error(site.line, f"{host} is more than one level deep; Cloudflare's edge "
                      "certificate covers *.codescriet.dev only, so it would fail TLS")
            continue
        if not LABEL_RE.match(label):
            res.error(site.line, f"subdomain label {label!r} must be lowercase letters, "
                      "digits and inner hyphens, 1-63 characters")
            continue
        if label in PROTECTED:
            msg = (f"{host} is a protected subdomain ({PROTECTED[label]}); changing it "
                   "needs an issue that names it explicitly")
            (res.warn if opts.allow_protected else res.error)(site.line, msg)
        labels.append(label)
    return labels


def check_existing(labels: list, site: Node, res: Result, opts):
    try:
        text = Path(opts.caddyfile).read_text(errors="replace")
    except OSError as exc:
        res.warn(site.line, f"could not read {opts.caddyfile} to check for clashes: "
                 f"{exc.strerror or exc}")
        return
    existing = set(re.findall(r"^\s*(?:https?://)?([a-z0-9.-]+)\." + re.escape(ZONE)
                              + r"\b[^\n]*\{\s*$", text, re.M))
    for label in labels:
        if label in existing:
            msg = (f"{label}.{ZONE} already has a block in {opts.caddyfile}; edit that block "
                   "in place, never append a duplicate")
            (res.warn if opts.allow_existing else res.error)(site.line, msg)


def upstreams_of(node: Node) -> list:
    """Upstream tokens of a reverse_proxy directive, including 'to' sub-directives."""
    ups = []
    for tok in node.tokens[1:]:
        if tok.startswith("@") or tok.startswith("/") or tok == "*":
            continue
        ups.append(tok)
    for child in node.children:
        if child.name == "to":
            ups.extend(child.tokens[1:])
    return ups


def check_upstream(tok: str, line: int, res: Result):
    if "{" in tok or "}" in tok:
        res.error(line, f"upstream {tok!r} uses a placeholder; dynamic upstreams are not allowed")
        return
    m = UPSTREAM_RE.match(tok)
    if not m:
        res.error(line, f"cannot read upstream {tok!r}; write 127.0.0.1:<port>")
        return
    scheme, host, port = (m.group("scheme") or ""), m.group("host"), m.group("port")
    if scheme and scheme not in ("http", "h2c"):
        res.error(line, f"upstream {tok!r} uses {scheme}://; local services are plain http")
    if host not in ("127.0.0.1", "localhost"):
        res.error(line, f"upstream {tok!r} must be 127.0.0.1 or localhost; never proxy "
                  "to another host or a public interface")
    if not port:
        res.error(line, f"upstream {tok!r} has no explicit port")
        return
    num = int(port)
    if not 1 <= num <= 65535:
        res.error(line, f"upstream port {num} is out of range")
    elif num in FORBIDDEN_PORTS:
        res.error(line, f"upstream port {num} is {FORBIDDEN_PORTS[num]}; never proxy to it")
    elif num in KNOWN_PORTS:
        res.warn(line, f"port {num} already serves {KNOWN_PORTS[num]}; make sure this new "
                 "subdomain is meant to expose it")


def nearest_root(node: Node):
    scope = node.parent
    while scope is not None:
        for sib in scope.children:
            if sib.name == "root" and len(sib.tokens) >= 2:
                return sib.tokens[-1], sib.line
        scope = scope.parent
    return None, None


def check_root_path(path: str, line: int, res: Result, opts):
    norm = os.path.normpath(path.replace("~", "/home/ubuntu", 1) if path.startswith("~") else path)
    parts = Path(norm).parts
    if not norm.startswith("/"):
        res.error(line, f"file_server root {path!r} is relative; use an absolute path")
        return
    if norm in SENSITIVE_EXACT or any(norm == p.rstrip("/") or norm.startswith(p)
                                      for p in SENSITIVE_PREFIX):
        res.error(line, f"file_server over sensitive path {norm}; serve a dedicated "
                  "directory such as /var/www/<name>")
        return
    if any(part.startswith(".") for part in parts[1:]):
        res.error(line, f"file_server root {norm} sits inside a hidden directory "
                  "such as a git, ssh or config directory; never serve it")
        return
    if norm == CLUBSITE_TREE or norm.startswith(CLUBSITE_TREE + "/"):
        msg = (f"{norm} is the live clubsite tree; only the existing main-site and "
               "playground blocks serve it")
        (res.warn if opts.allow_protected else res.error)(line, msg)
        return
    if not norm.startswith("/var/www/"):
        res.warn(line, f"static root {norm} is not a dedicated directory under /var/www/; "
                 "Caddy runs as user caddy, so every parent directory needs o+x and every "
                 "file o+r (chmod 644)")


def check_body(site: Node, res: Result, opts):
    nodes = list(walk(site.children))
    proxies = [n for n in nodes if n.name == "reverse_proxy"]
    servers = [n for n in nodes if n.name == "file_server"]
    if not proxies and not opts.static:
        res.error(site.line, "no reverse_proxy directive; a subdomain block proxies to "
                  "127.0.0.1:<port> (pass --static for a file_server-only site)")
    if opts.static and not servers and not proxies:
        res.error(site.line, "--static was given but the block has no file_server")
    for p in proxies:
        ups = upstreams_of(p)
        if not ups:
            res.error(p.line, "reverse_proxy has no upstream; write reverse_proxy 127.0.0.1:<port>")
        for tok in ups:
            check_upstream(tok, p.line, res)
    for s in servers:
        if "browse" in s.tokens[1:]:
            res.warn(s.line, "file_server browse lists every file in the directory; "
                     "drop 'browse' unless a listing is the point")
        root, rline = nearest_root(s)
        if root is None:
            res.error(s.line, "file_server without a root directive serves Caddy's working "
                      "directory; set root * /var/www/<name>")
        else:
            check_root_path(root, rline, res, opts)

    hsts = []
    for n in nodes:
        for tok in n.tokens:
            if tok.lower().lstrip("+-?>") == "strict-transport-security":
                hsts.append((n, tok))
    if not hsts:
        res.error(site.line, "no Strict-Transport-Security header; add "
                  f"header {{ Strict-Transport-Security \"max-age={HSTS_MIN}\" }}")
    for n, tok in hsts:
        if tok.startswith("-"):
            res.error(n.line, "the block removes Strict-Transport-Security; it must set it")
            continue
        header_dir = n if n.name == "header" else n.parent
        if header_dir is not None and header_dir.name == "header" and len(header_dir.tokens) > 1:
            first = header_dir.tokens[1]
            if first.startswith("/") or first.startswith("@"):
                res.warn(n.line, "HSTS is scoped to a matcher; set it for the whole site")
        value = " ".join(n.tokens[n.tokens.index(tok) + 1:])
        m = re.search(r"max-age=(\d+)", value)
        if not m:
            res.error(n.line, "Strict-Transport-Security has no max-age value")
        elif int(m.group(1)) < HSTS_MIN:
            res.warn(n.line, f"HSTS max-age {m.group(1)} is below the house value {HSTS_MIN}")

    for n in nodes:
        if n.name == "admin":
            res.error(n.line, "admin directive found; the admin API stays off on this VM")
        if n.name == "tls":
            res.error(n.line, "tls directive found; Cloudflare terminates TLS and :443 is the VPN")
        if n.name == "bind":
            res.error(n.line, "bind directive found; subdomain blocks listen on Caddy's :80 only")
        if n.name == "import":
            res.warn(n.line, "import pulls in text this linter cannot see; inline it")
        if n.name in ("basicauth", "basic_auth"):
            for child in n.children:
                if len(child.tokens) >= 2 and child.tokens[1].startswith("$2"):
                    res.warn(child.line, "block contains a password hash; never paste it "
                             "into an issue or report")
        for tok in n.tokens:
            if re.search(r"(^|[:/])2019(\b|$)", tok):
                res.error(n.line, f"token {tok!r} points at :2019, the admin API port")


def lint(text: str, opts) -> tuple[Result, list]:
    res = Result()
    try:
        top = parse(text)
    except ParseError as exc:
        res.error(0, str(exc))
        return res, []
    sites = [n for n in top if n.is_block]
    stray = [n for n in top if not n.is_block]
    for n in stray:
        res.error(n.line, f"directive {n.name!r} outside any site block")
    if not sites:
        res.error(0, "no site block found")
        return res, []
    if len(sites) > 1:
        res.error(sites[1].line, f"{len(sites)} blocks found; submit exactly one site block "
                  "per request")
    site = sites[0]
    labels = check_address(site, res, opts)
    if opts.caddyfile and labels:
        check_existing(labels, site, res, opts)
    check_body(site, res, opts)
    return res, labels


def ceo_commands(block_path: str, labels: list, static_roots: list) -> list:
    name = labels[0] if labels else "<name>"
    host = f"{name}.{ZONE}"
    cmds = [
        "# 1. DNS (Cloudflare dashboard): add a proxied (orange cloud) record for "
        f"'{name}', same target as the existing 'api' record.",
        "# 2. Back up the live Caddyfile:",
        f"cp {CADDYFILE} {CADDYFILE}.bak-$(date -u +%Y%m%d-%H%M%S)",
        "# 3. Append the reviewed block:",
        f"printf '\\n' >> {CADDYFILE} && cat {block_path} >> {CADDYFILE}",
        "# 4. Validate. Stop here if this prints anything but 'Valid configuration':",
        f"caddy validate --config {CADDYFILE} --adapter caddyfile",
        "# 5. Restart (never reload: 'admin off' means :2019 is not listening, so reload fails):",
        "sudo systemctl restart caddy",
        "systemctl status caddy --no-pager | head -5",
        "# 6. Verify the new site and that nothing else broke:",
        f"curl -sS -o /dev/null -w '%{{http_code}}\\n' https://{host}/",
        f"curl -sSI https://{host}/ | grep -i strict-transport-security",
        "curl -sS -o /dev/null -w '%{http_code}\\n' https://codescriet.dev/",
        "systemctl is-active xray club-api club-playground",
    ]
    for root in static_roots:
        cmds += [f"namei -l {root}    # every directory needs o+x for user caddy",
                 f"find {root} -type f ! -perm -o+r    # must print nothing (files chmod 644)"]
    cmds += ["# Rollback if any check fails:",
             f"cp \"$(ls -t {CADDYFILE}.bak-* | head -1)\" {CADDYFILE} && "
             f"caddy validate --config {CADDYFILE} --adapter caddyfile && sudo systemctl restart caddy"]
    return cmds


def build_parser():
    p = argparse.ArgumentParser(
        prog="caddy_block_lint.py",
        description="Pure text lint of a proposed codescriet.dev subdomain Caddy block. "
                    "Never runs caddy. Prints the CEO's validate+restart commands when clean.")
    p.add_argument("block", help="file holding the proposed site block")
    p.add_argument("--static", action="store_true",
                   help="allow a file_server-only block (no reverse_proxy)")
    p.add_argument("--caddyfile", default=None,
                   help=f"read this Caddyfile (read-only) to catch duplicate hostnames, "
                        f"for example {CADDYFILE}")
    p.add_argument("--allow-protected", action="store_true",
                   help="downgrade protected-subdomain errors to warnings (issue names it)")
    p.add_argument("--allow-existing", action="store_true",
                   help="the block intentionally replaces an existing one")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    return p


def main(argv=None) -> int:
    opts = build_parser().parse_args(argv)
    try:
        text = Path(opts.block).read_text(errors="replace")
    except OSError as exc:
        print(f"caddy_block_lint: cannot read {opts.block}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    res, labels = lint(text, opts)
    for line, msg in sorted(res.errors):
        print(f"ERROR line {line}: {msg}")
    for line, msg in sorted(res.warnings):
        print(f"WARN  line {line}: {msg}")
    failing = res.errors + (res.warnings if opts.strict else [])
    if failing:
        print(f"\n{len(res.errors)} error(s), {len(res.warnings)} warning(s). Fix the block; "
              "no commands are printed until it lints clean.")
        first = sorted(failing)[0][1]
        print(f"caddy_block_lint: {len(failing)} blocking finding(s): {first[:200]}", file=sys.stderr)
        return 1
    roots = []
    if opts.static:
        try:
            for n in walk(parse(text)):
                if n.name == "root" and len(n.tokens) >= 2:
                    roots.append(n.tokens[-1])
        except ParseError:
            pass
    print(f"OK: block for {', '.join(l + '.' + ZONE for l in labels)} passes "
          f"({len(res.warnings)} warning(s)).\n")
    print("## Commands for the CEO (platform-1 never runs these)\n")
    print("\n".join(ceo_commands(str(Path(opts.block).resolve()), labels, roots)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
