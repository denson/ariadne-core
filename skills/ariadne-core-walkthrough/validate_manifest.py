#!/usr/bin/env python3
"""Validate image_manifest.yaml and project_knowledge_graph.yaml.

These files ship INSIDE this skill directory so the plugin is self-contained.
Run from anywhere:

    python skills/ariadne-core-walkthrough/validate_manifest.py

Checks:
  1. Every `file:` path in image_manifest.yaml exists (resolved against this
     skill directory — files must ship inside the skill).
  2. Every image id referenced from the knowledge graph resolves to a
     manifest entry.
  3. Every `sources.file:` path in the knowledge graph, if present, exists
     (resolved against the repo root when a repo is available). These are
     dev-tree paths — at install time they won't resolve and the `github_url`
     is the authoritative pointer. Missing source files are warnings, not
     errors.
  4. Every `see_also` id in the knowledge graph resolves to another concept.
  5. Image ids and concept ids are unique within their respective files.

Exit 0 on success, 1 on any error.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("Missing dependency: pyyaml. Install with `pip install pyyaml`.\n")
    sys.exit(2)


# This file lives at: <repo>/skills/ariadne-core-walkthrough/validate_manifest.py
SKILL_DIR = Path(__file__).resolve().parent
# Best-effort repo root (for validating graph source paths in dev trees).
# At install time this may not resolve to anything useful, which is fine —
# we only warn for missing source files.
REPO_ROOT = SKILL_DIR.parents[2] if len(SKILL_DIR.parents) >= 3 else SKILL_DIR

MANIFEST = SKILL_DIR / "image_manifest.yaml"
GRAPH = SKILL_DIR / "project_knowledge_graph.yaml"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        sys.stderr.write(f"ERROR: missing file {path}\n")
        sys.exit(1)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    manifest = load_yaml(MANIFEST)
    graph = load_yaml(GRAPH)

    images = manifest.get("images", [])
    concepts = graph.get("concepts", [])

    # --- Manifest: unique ids, files exist inside skill ---
    image_ids: set[str] = set()
    for img in images:
        img_id = img.get("id")
        if not img_id:
            errors.append(f"manifest: image entry missing id: {img}")
            continue
        if img_id in image_ids:
            errors.append(f"manifest: duplicate image id '{img_id}'")
        image_ids.add(img_id)

        file_path = img.get("file")
        if not file_path:
            errors.append(f"manifest[{img_id}]: missing 'file' field")
            continue
        abs_path = SKILL_DIR / file_path
        if not abs_path.exists():
            errors.append(
                f"manifest[{img_id}]: file not found inside skill: {file_path}"
            )

    # --- Graph: unique concept ids ---
    concept_ids: set[str] = set()
    for c in concepts:
        cid = c.get("id")
        if not cid:
            errors.append(f"graph: concept missing id: {c}")
            continue
        if cid in concept_ids:
            errors.append(f"graph: duplicate concept id '{cid}'")
        concept_ids.add(cid)

    for c in concepts:
        cid = c.get("id", "<unknown>")

        # images: must resolve to manifest ids
        for ref in c.get("images", []) or []:
            if ref not in image_ids:
                errors.append(f"graph[{cid}]: image ref '{ref}' not in manifest")

        # sources: dev-tree file paths; missing is a warning, not an error
        for src in c.get("sources", []) or []:
            file_path = src.get("file")
            if file_path:
                abs_path = REPO_ROOT / file_path
                if not abs_path.exists():
                    warnings.append(
                        f"graph[{cid}]: source file not found in dev tree "
                        f"(ok at install time): {file_path}"
                    )

        # see_also: must resolve to other concept ids
        for ref in c.get("see_also", []) or []:
            if ref not in concept_ids:
                errors.append(f"graph[{cid}]: see_also '{ref}' not a known concept id")

    # --- Report ---
    print(f"Skill dir: {SKILL_DIR}")
    print(f"Manifest:  {len(images)} images, {len(image_ids)} unique ids")
    print(f"Graph:     {len(concepts)} concepts, {len(concept_ids)} unique ids")

    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  WARN: {w}")

    if errors:
        print(f"\n{len(errors)} error(s):")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    print("\nOK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
