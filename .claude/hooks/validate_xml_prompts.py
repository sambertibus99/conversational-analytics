#!/usr/bin/env python3
"""
Post-Edit/Write Hook: Validiert XML-Tag-Struktur in Prompt-Dateien (DEC-015).

Liest Hook-Input von stdin (JSON mit tool_name, tool_input).
Prüft nur Dateien in prompts/*.py (außer __init__.py).

Pflicht-Tags: <role>, <task>
Empfohlene Tags: <tools>, <examples>
Prüft ob Tags balanced sind (öffnend/schließend).

Exit 0 = OK oder nicht relevant
Exit 2 = Warnung (blockiert nicht bei PostToolUse)
"""

import json
import re
import sys
import os


REQUIRED_TAGS = ["role", "task"]
RECOMMENDED_TAGS = ["tools", "examples"]
# Strukturelle Tags deren Balance geprüft wird (DEC-015 Sektionen)
STRUCTURAL_TAGS = [
    "role", "task", "context", "instructions", "tools", "examples",
    "error_handling", "critical_rules", "data_mode", "key_lookup",
]
PROMPTS_DIR = "prompts"


def get_file_path_from_input():
    """Liest den Hook-Input von stdin und extrahiert file_path."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        data = json.loads(raw)
        tool_input = data.get("tool_input", {})
        return tool_input.get("file_path", "")
    except (json.JSONDecodeError, AttributeError):
        return None


def is_prompt_file(file_path):
    """Prüft ob die Datei eine Prompt-Datei in prompts/ ist."""
    if not file_path:
        return False

    # Normalisiere den Pfad
    norm = os.path.normpath(file_path)

    # Prüfe ob die Datei in prompts/ liegt und .py ist
    parts = norm.split(os.sep)
    if PROMPTS_DIR not in parts:
        return False

    basename = os.path.basename(norm)
    if not basename.endswith(".py"):
        return False

    # __init__.py überspringen
    if basename == "__init__.py":
        return False

    return True


def find_xml_tags(content):
    """Findet alle XML-Tags im String-Content der Datei."""
    # Suche in String-Literalen (f-Strings, normale Strings)
    opening = re.findall(r"<(\w+)>", content)
    closing = re.findall(r"</(\w+)>", content)
    return opening, closing


def validate_prompt(file_path):
    """Validiert die XML-Tag-Struktur einer Prompt-Datei."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return []  # Datei existiert nicht (mehr), kein Fehler

    opening_tags, closing_tags = find_xml_tags(content)

    issues = []

    # Pflicht-Tags prüfen
    for tag in REQUIRED_TAGS:
        if tag not in opening_tags:
            issues.append(f"FEHLER: Pflicht-Tag <{tag}> fehlt (DEC-015)")
        elif tag not in closing_tags:
            issues.append(f"FEHLER: Schließendes </{tag}> fehlt")

    # Empfohlene Tags prüfen
    for tag in RECOMMENDED_TAGS:
        if tag not in opening_tags:
            issues.append(f"WARNUNG: Empfohlener Tag <{tag}> fehlt")

    # Balanced Tags prüfen (nur strukturelle DEC-015 Tags, nicht Beispiel-Content)
    opening_counts = {}
    closing_counts = {}
    for tag in opening_tags:
        opening_counts[tag] = opening_counts.get(tag, 0) + 1
    for tag in closing_tags:
        closing_counts[tag] = closing_counts.get(tag, 0) + 1

    for tag in STRUCTURAL_TAGS:
        o = opening_counts.get(tag, 0)
        c = closing_counts.get(tag, 0)
        if o > 0 and o != c:
            issues.append(
                f"FEHLER: Tag <{tag}> nicht balanced ({o}x geöffnet, {c}x geschlossen)"
            )

    return issues


def main():
    file_path = get_file_path_from_input()

    if not is_prompt_file(file_path):
        sys.exit(0)

    issues = validate_prompt(file_path)

    if not issues:
        basename = os.path.basename(file_path)
        print(f"DEC-015 OK: {basename} - Alle XML-Tags korrekt.")
        sys.exit(0)

    # Feedback ausgeben
    basename = os.path.basename(file_path)
    print(f"DEC-015 Validierung fuer {basename}:")
    for issue in issues:
        print(f"  - {issue}")

    # Exit 2 = Warnung, blockiert nicht bei PostToolUse
    has_errors = any(issue.startswith("FEHLER") for issue in issues)
    if has_errors:
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
