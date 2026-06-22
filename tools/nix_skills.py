#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^sha256-[A-Za-z0-9+/=]+$")
CATALOG_START = "<!-- nix-skills-catalog:start -->"
CATALOG_END = "<!-- nix-skills-catalog:end -->"
REQUIRED_FIELDS = [
    "slug",
    "displayName",
    "description",
    "license",
    "author",
    "compatibleTargets",
    "source",
]
SOURCE_REQUIRED_FIELDS = [ "type", "owner", "repo", "rev", "path", "narHash" ]


class RegistryError(Exception):
    pass


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def repo_root(args: argparse.Namespace) -> Path:
    return Path(args.repo).expanduser().resolve()


def registry_dir(root: Path) -> Path:
    return root / "registry" / "skills"


def generated_registry_path(root: Path) -> Path:
    return root / "generated" / "registry.nix"


def catalog_path(root: Path) -> Path:
    return root / "CATALOG.md"


def read_json(path: Path) -> dict[str, Any]:
    try:
      with path.open("r", encoding="utf-8") as handle:
          value = json.load(handle)
    except json.JSONDecodeError as exc:
      raise RegistryError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
      raise RegistryError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_entries(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    directory = registry_dir(root)
    if not directory.exists():
      raise RegistryError(f"missing registry directory: {directory}")

    for path in sorted(directory.glob("*.json")):
      entry = read_json(path)
      slug = entry.get("slug")
      if not isinstance(slug, str):
        raise RegistryError(f"{path}: slug must be a string")
      if slug in entries:
        raise RegistryError(f"duplicate slug '{slug}' in {path}")
      if path.stem != slug:
        raise RegistryError(f"{path}: file name must match slug '{slug}'")
      entries[slug] = entry
    return dict(sorted(entries.items()))


def require_string(entry: dict[str, Any], field: str, path: Path) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or value == "":
      raise RegistryError(f"{path}: {field} must be a non-empty string")
    return value


def require_string_list(entry: dict[str, Any], field: str, path: Path, *, nonempty: bool = False) -> list[str]:
    value = entry.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
      raise RegistryError(f"{path}: {field} must be a list of strings")
    if nonempty and len(value) == 0:
      raise RegistryError(f"{path}: {field} must not be empty")
    if len(value) != len(set(value)):
      raise RegistryError(f"{path}: {field} contains duplicate values")
    return value


def validate_source(entry: dict[str, Any], path: Path) -> None:
    source = entry.get("source")
    if not isinstance(source, dict):
      raise RegistryError(f"{path}: source must be an object")

    for field in SOURCE_REQUIRED_FIELDS:
      require_string(source, field, path)

    if source["type"] != "github":
      raise RegistryError(f"{path}: source.type must be 'github'")
    if not SHA_RE.match(source["rev"]):
      raise RegistryError(f"{path}: source.rev must be a 40-character lowercase commit SHA")
    if not HASH_RE.match(source["narHash"]):
      raise RegistryError(f"{path}: source.narHash must be an SRI sha256 hash")
    if source["path"].startswith("/") or ".." in Path(source["path"]).parts:
      raise RegistryError(f"{path}: source.path must be a safe relative path")


def validate_entries(entries: dict[str, dict[str, Any]], root: Path) -> None:
    if not entries:
      raise RegistryError("registry must contain at least one skill")

    for slug, entry in entries.items():
      path = registry_dir(root) / f"{slug}.json"
      for field in REQUIRED_FIELDS:
        if field not in entry:
          raise RegistryError(f"{path}: missing required field {field}")

      if not SLUG_RE.match(slug):
        raise RegistryError(f"{path}: invalid slug '{slug}'")
      if entry["slug"] != slug:
        raise RegistryError(f"{path}: slug field does not match entry key")

      for field in [ "displayName", "description", "license", "author" ]:
        require_string(entry, field, path)

      if "homepage" in entry:
        require_string(entry, "homepage", path)
      if "version" in entry:
        require_string(entry, "version", path)

      compatible_targets = require_string_list(entry, "compatibleTargets", path, nonempty=True)
      for target in compatible_targets:
        if target != "*" and not SLUG_RE.match(target):
          raise RegistryError(f"{path}: invalid compatible target '{target}'")

      for dependency in require_string_list(entry, "dependencies", path):
        if dependency == slug:
          raise RegistryError(f"{path}: skill cannot depend on itself")
        if dependency not in entries:
          raise RegistryError(f"{path}: unknown dependency '{dependency}'")

      for tag in require_string_list(entry, "tags", path):
        if tag == "":
          raise RegistryError(f"{path}: tags cannot contain empty strings")

      validate_source(entry, path)

    check_cycles(entries)


def check_cycles(entries: dict[str, dict[str, Any]]) -> None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(slug: str) -> None:
      if slug in visited:
        return
      if slug in visiting:
        cycle = visiting[visiting.index(slug):] + [slug]
        raise RegistryError(f"dependency cycle: {' -> '.join(cycle)}")
      visiting.append(slug)
      for dependency in entries[slug].get("dependencies", []):
        visit(dependency)
      visiting.pop()
      visited.add(slug)

    for slug in entries:
      visit(slug)


def canonical_registry_json(entries: dict[str, dict[str, Any]]) -> str:
    return json.dumps(entries, indent=2, sort_keys=True)


def generated_registry_nix(entries: dict[str, dict[str, Any]]) -> str:
    json_text = canonical_registry_json(entries)
    return (
        "# This file is generated by `nix-skills generate`.\n"
        "# Edit registry/skills/*.json, then regenerate.\n"
        "builtins.fromJSON ''\n"
        f"{escape_nix_indented_string(json_text)}\n"
        "''\n"
    )


def escape_nix_indented_string(value: str) -> str:
    return value.replace("''", "'''").replace("${", "''${")


def source_url(entry: dict[str, Any]) -> str:
    source = entry["source"]
    encoded_path = "/".join(urllib.parse.quote(part) for part in source["path"].split("/"))
    return f"https://github.com/{source['owner']}/{source['repo']}/tree/{source['rev']}/{encoded_path}"


def catalog_markdown(entries: dict[str, dict[str, Any]]) -> str:
    lines = [
      CATALOG_START,
      "| Skill | Description | Targets | Dependencies | Source |",
      "| --- | --- | --- | --- | --- |",
    ]
    for slug, entry in entries.items():
      source = entry["source"]
      targets = ", ".join(entry.get("compatibleTargets", [])) or "-"
      dependencies = ", ".join(entry.get("dependencies", [])) or "-"
      lines.append(
          "| `{slug}` | {description} | {targets} | {dependencies} | [{owner}/{repo}]({url}) |".format(
              slug=slug,
              description=markdown_cell(entry["description"]),
              targets=markdown_cell(targets),
              dependencies=markdown_cell(dependencies),
              owner=source["owner"],
              repo=source["repo"],
              url=source_url(entry),
          )
      )
    lines.append(CATALOG_END)
    return "\n".join(lines)


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def update_catalog(root: Path, entries: dict[str, dict[str, Any]]) -> None:
    path = catalog_path(root)
    text = path.read_text(encoding="utf-8")
    start = text.find(CATALOG_START)
    end = text.find(CATALOG_END)
    if start == -1 or end == -1 or end < start:
      raise RegistryError("CATALOG.md must contain nix-skills catalog markers")
    end += len(CATALOG_END)
    new_text = text[:start] + catalog_markdown(entries) + text[end:]
    path.write_text(new_text, encoding="utf-8")


def expected_generated_files(root: Path, entries: dict[str, dict[str, Any]]) -> dict[Path, str]:
    catalog = catalog_path(root).read_text(encoding="utf-8")
    start = catalog.find(CATALOG_START)
    end = catalog.find(CATALOG_END)
    if start == -1 or end == -1 or end < start:
      raise RegistryError("CATALOG.md must contain nix-skills catalog markers")
    end += len(CATALOG_END)
    expected_catalog = catalog[:start] + catalog_markdown(entries) + catalog[end:]
    return {
      generated_registry_path(root): generated_registry_nix(entries),
      catalog_path(root): expected_catalog,
    }


def run_generate(args: argparse.Namespace) -> None:
    root = repo_root(args)
    entries = load_entries(root)
    validate_entries(entries, root)
    generated_registry_path(root).parent.mkdir(parents=True, exist_ok=True)
    generated_registry_path(root).write_text(generated_registry_nix(entries), encoding="utf-8")
    update_catalog(root, entries)
    print(f"generated {generated_registry_path(root)} and CATALOG.md")


def run_check(args: argparse.Namespace) -> None:
    root = repo_root(args)
    try:
      entries = load_entries(root)
      validate_entries(entries, root)
      for path, expected in expected_generated_files(root, entries).items():
        if not path.exists():
          raise RegistryError(f"missing generated file: {path}")
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
          raise RegistryError(f"{path} is out of date; run `nix-skills generate`")
      if args.fetch:
        validate_fetches(entries)
    except RegistryError as exc:
      die(str(exc))
    print(f"ok: {len(entries)} skills")


def validate_fetches(entries: dict[str, dict[str, Any]]) -> None:
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", "/tmp/nix-skills-cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("XDG_CACHE_HOME", str(cache_dir))

    for slug, entry in entries.items():
      source = entry["source"]
      fetched = prefetch(source["owner"], source["repo"], source["rev"], env=env)
      if fetched["hash"] != source["narHash"]:
        raise RegistryError(
          f"{slug}: hash mismatch: registry has {source['narHash']}, prefetch returned {fetched['hash']}"
        )
      skill_md = Path(fetched["storePath"]) / source["path"] / "SKILL.md"
      if not skill_md.exists():
        raise RegistryError(f"{slug}: SKILL.md not found at source path {source['path']}")


def prefetch(owner: str, repo: str, rev: str, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    ref = f"github:{owner}/{repo}/{rev}"
    command = [ "nix", "flake", "prefetch", "--no-use-registries", "--json", ref ]
    result = subprocess.run(command, check=True, text=True, capture_output=True, env=env)
    return json.loads(result.stdout)


def github_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={ "Accept": "application/vnd.github+json" })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
      request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request) as response:
      return json.loads(response.read().decode("utf-8"))


def default_branch(owner: str, repo: str) -> str:
    data = github_json(f"https://api.github.com/repos/{owner}/{repo}")
    branch = data.get("default_branch")
    if not isinstance(branch, str) or branch == "":
      raise RegistryError(f"could not determine default branch for {owner}/{repo}")
    return branch


def resolve_rev(owner: str, repo: str, ref: str | None) -> str:
    selected_ref = ref or default_branch(owner, repo)
    if SHA_RE.match(selected_ref):
      return selected_ref
    encoded_ref = urllib.parse.quote(selected_ref, safe="")
    data = github_json(f"https://api.github.com/repos/{owner}/{repo}/commits/{encoded_ref}")
    sha = data.get("sha")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
      raise RegistryError(f"could not resolve {owner}/{repo}@{selected_ref} to a commit SHA")
    return sha


def parse_tree_url(url: str) -> tuple[str, str, str, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != "github.com":
      raise RegistryError("only github.com tree URLs are supported")
    parts = [ part for part in parsed.path.split("/") if part ]
    if len(parts) < 5 or parts[2] != "tree":
      raise RegistryError("expected URL shape: https://github.com/owner/repo/tree/ref/path/to/skill")
    owner, repo, _tree, ref = parts[:4]
    skill_path = "/".join(parts[4:])
    if skill_path == "":
      raise RegistryError("GitHub tree URL must include a skill folder path")
    return owner, repo, ref, skill_path


def parse_frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
      return {}
    end = text.find("\n---", 3)
    if end == -1:
      return {}
    body = text[3:end].strip()
    metadata: dict[str, str] = {}
    for line in body.splitlines():
      if ":" not in line:
        continue
      key, value = line.split(":", 1)
      metadata[key.strip()] = value.strip().strip("\"'")
    return metadata


def prompt(default: str, label: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def build_entry_from_source(
    owner: str,
    repo: str,
    rev: str,
    skill_path: str,
    nar_hash: str,
    store_path: str,
) -> dict[str, Any]:
    skill_md = Path(store_path) / skill_path / "SKILL.md"
    if not skill_md.exists():
      raise RegistryError(f"SKILL.md not found at {skill_path}")
    metadata = parse_frontmatter(skill_md)
    default_slug = metadata.get("name") or Path(skill_path).name
    default_description = metadata.get("description") or ""

    slug = prompt(default_slug, "Slug")
    display_name = prompt(slug.replace("-", " ").title(), "Display name")
    description = prompt(default_description, "Description")
    author = prompt(owner, "Author")
    license_name = prompt("MIT", "License")
    targets = prompt("*", "Compatible targets, comma-separated")
    tags = prompt("", "Tags, comma-separated")
    dependencies = prompt("", "Dependencies, comma-separated")

    entry: dict[str, Any] = {
      "slug": slug,
      "displayName": display_name,
      "description": description,
      "license": license_name,
      "author": author,
      "homepage": f"https://github.com/{owner}/{repo}/tree/{rev}/{skill_path}",
      "compatibleTargets": split_csv(targets),
      "source": {
        "type": "github",
        "owner": owner,
        "repo": repo,
        "rev": rev,
        "path": skill_path,
        "narHash": nar_hash,
      },
    }
    if tags.strip():
      entry["tags"] = split_csv(tags)
    if dependencies.strip():
      entry["dependencies"] = split_csv(dependencies)
    return entry


def split_csv(value: str) -> list[str]:
    return [ item.strip() for item in value.split(",") if item.strip() ]


def run_add(args: argparse.Namespace) -> None:
    root = repo_root(args)
    try:
      owner, repo, ref, skill_path = parse_tree_url(args.github_tree_url)
      rev = resolve_rev(owner, repo, ref)
      fetched = prefetch(owner, repo, rev)
      entry = build_entry_from_source(owner, repo, rev, skill_path, fetched["hash"], fetched["storePath"])
      output = registry_dir(root) / f"{entry['slug']}.json"
      if output.exists() and not args.force:
        raise RegistryError(f"{output} already exists; pass --force to overwrite")
      write_json(output, entry)
      entries = load_entries(root)
      validate_entries(entries, root)
    except RegistryError as exc:
      die(str(exc))
    print(f"wrote {output}")
    print("run `nix-skills generate` next")


def update_entry(entry: dict[str, Any], rev: str | None) -> bool:
    source = entry["source"]
    new_rev = resolve_rev(source["owner"], source["repo"], rev)
    fetched = prefetch(source["owner"], source["repo"], new_rev)
    changed = source["rev"] != new_rev or source["narHash"] != fetched["hash"]
    source["rev"] = new_rev
    source["narHash"] = fetched["hash"]
    if "homepage" in entry:
      entry["homepage"] = source_url(entry)
    return changed


def run_update(args: argparse.Namespace) -> None:
    root = repo_root(args)
    try:
      entries = load_entries(root)
      if args.all:
        selected = list(entries)
      elif args.slug:
        selected = [ args.slug ]
      else:
        raise RegistryError("update requires a skill slug or --all")
      for slug in selected:
        if slug not in entries:
          raise RegistryError(f"unknown skill slug: {slug}")
        changed = update_entry(entries[slug], args.rev)
        if changed:
          write_json(registry_dir(root) / f"{slug}.json", entries[slug])
          print(f"updated {slug}")
        else:
          print(f"unchanged {slug}")
      run_generate(args)
    except RegistryError as exc:
      die(str(exc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nix-skills")
    parser.add_argument("--repo", default=".", help="repository root, default: current directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="validate registry and generated files")
    check_parser.add_argument("--fetch", action="store_true", help="also prefetch sources and verify SKILL.md")
    check_parser.set_defaults(func=run_check)

    generate_parser = subparsers.add_parser("generate", help="regenerate committed artifacts")
    generate_parser.set_defaults(func=run_generate)

    add_parser = subparsers.add_parser("add", help="add a GitHub-hosted skill")
    add_parser.add_argument("github_tree_url")
    add_parser.add_argument("--force", action="store_true", help="overwrite an existing slug JSON file")
    add_parser.set_defaults(func=run_add)

    update_parser = subparsers.add_parser("update", help="update one skill or --all")
    update_parser.add_argument("slug", nargs="?", help="skill slug")
    update_parser.add_argument("--all", action="store_true", help="update all registry skills")
    update_parser.add_argument("--rev", help="specific commit SHA or GitHub ref to pin")
    update_parser.set_defaults(func=run_update)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
