"""
Hilfsskript für E2E-Test App-Lifecycle-Management.

Wird vom e2e-tester Agent via Bash aufgerufen.

Verwendung:
    python evaluation/e2e_runner.py start          # App starten, PID speichern
    python evaluation/e2e_runner.py health-check    # Warten bis App erreichbar (max 30s)
    python evaluation/e2e_runner.py stop            # App stoppen via gespeicherter PID
    python evaluation/e2e_runner.py list-tests <arg> # Testfragen als JSON ausgeben
"""

import sys
import json
import signal
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PID_FILE = Path("/tmp/chainlit_e2e.pid")
LOG_FILE = Path("/tmp/chainlit_e2e.log")
APP_URL = "http://localhost:8000"


def start():
    """Startet die Chainlit-App im Hintergrund."""
    # Prüfen ob bereits eine Instanz läuft
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            # Prüfen ob Prozess noch lebt
            import os
            os.kill(pid, 0)
            print(f"App läuft bereits (PID {pid}). Stoppe zuerst mit 'stop'.")
            sys.exit(1)
        except OSError:
            # Prozess existiert nicht mehr, PID-Datei aufräumen
            PID_FILE.unlink()

    venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
    if not venv_python.exists():
        # Fallback: chainlit direkt aus venv
        venv_chainlit = PROJECT_ROOT / "venv" / "bin" / "chainlit"
        if not venv_chainlit.exists():
            print("Fehler: venv nicht gefunden. Bitte 'source venv/bin/activate' ausführen.")
            sys.exit(1)
        cmd = [str(venv_chainlit), "run", "app.py"]
    else:
        cmd = [str(venv_python), "-m", "chainlit", "run", "app.py"]

    with open(LOG_FILE, "w") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    PID_FILE.write_text(str(proc.pid))
    print(f"App gestartet (PID {proc.pid})")
    print(f"Log: {LOG_FILE}")
    print(f"PID-Datei: {PID_FILE}")


def health_check():
    """Pollt die App-URL bis HTTP 200 (max 30s)."""
    max_wait = 30
    interval = 2
    elapsed = 0

    print(f"Warte auf {APP_URL} (max {max_wait}s)...")

    while elapsed < max_wait:
        try:
            req = urllib.request.urlopen(APP_URL, timeout=5)
            if req.status == 200:
                print(f"App erreichbar nach {elapsed}s")
                return
        except (urllib.error.URLError, ConnectionError, OSError):
            pass

        time.sleep(interval)
        elapsed += interval
        print(f"  ... {elapsed}s")

    print(f"Fehler: App nicht erreichbar nach {max_wait}s")
    print(f"Prüfe Log: {LOG_FILE}")
    sys.exit(1)


def stop():
    """Stoppt die App via gespeicherter PID."""
    if not PID_FILE.exists():
        print("Keine PID-Datei gefunden. App läuft möglicherweise nicht.")
        return

    pid = int(PID_FILE.read_text().strip())

    try:
        import os
        # SIGTERM senden (graceful shutdown)
        os.kill(pid, signal.SIGTERM)
        print(f"SIGTERM an PID {pid} gesendet")

        # Kurz warten, dann prüfen ob Prozess beendet
        time.sleep(2)
        try:
            os.kill(pid, 0)
            # Prozess lebt noch → SIGKILL
            os.kill(pid, signal.SIGKILL)
            print(f"SIGKILL an PID {pid} gesendet")
        except OSError:
            pass  # Prozess bereits beendet

    except OSError as e:
        print(f"Konnte PID {pid} nicht stoppen: {e}")

    PID_FILE.unlink(missing_ok=True)
    print("App gestoppt")


def list_tests(argument: str):
    """Gibt Testfragen als JSON aus, gefiltert nach Argument."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from evaluation.test_queries import (
        ALL_QUERIES,
        get_queries_by_category,
        get_query_by_id,
    )

    # Kategorie-Mapping
    category_map = {
        "einfach": "einfach",
        "mittel": "mittel",
        "komplex": "komplex",
        "abstention": "abstention",
    }

    if argument == "all":
        queries = ALL_QUERIES
    elif argument.lower() in category_map:
        queries = get_queries_by_category(category_map[argument.lower()])
    else:
        # Einzelne ID (E1, M3, etc.)
        query = get_query_by_id(argument.upper())
        if query is None:
            print(json.dumps({"error": f"Unbekanntes Argument: {argument}"}))
            sys.exit(1)
        queries = [query]

    # Als JSON ausgeben
    output = []
    for q in queries:
        output.append({
            "id": q.id,
            "query": q.query,
            "category": q.category,
            "expected_agents": q.expected_agents,
            "should_abstain": q.should_abstain,
            "expected_behavior": q.expected_behavior,
        })

    print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 2:
        print("Verwendung: python e2e_runner.py <start|health-check|stop|list-tests [arg]>")
        sys.exit(1)

    command = sys.argv[1]

    if command == "start":
        start()
    elif command == "health-check":
        health_check()
    elif command == "stop":
        stop()
    elif command == "list-tests":
        if len(sys.argv) < 3:
            print("Verwendung: python e2e_runner.py list-tests <einfach|mittel|komplex|abstention|all|E1|M3|...>")
            sys.exit(1)
        list_tests(sys.argv[2])
    else:
        print(f"Unbekannter Befehl: {command}")
        print("Verfügbar: start, health-check, stop, list-tests")
        sys.exit(1)


if __name__ == "__main__":
    main()
