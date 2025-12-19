# CLAUDE.md - Projekt-Kontext

> **Letzte Aktualisierung:** 19.12.2025

## Projekt

**Conversational Analytics für IIoT** (Masterarbeit)
- **Ziel:** MCP-basiertes System für natürlichsprachliche Datenanalyse
- **Abgabe:** 31. März 2025
- **Status:** System-Review läuft

---

## 📚 Dokumentations-Katalog

**WICHTIG: Lade Dateien SELBSTSTÄNDIG wenn du sie brauchst!**

| Datei | Inhalt | Lade wenn... |
|-------|--------|--------------|
| `docs/05_ARCHITEKTUR.md` | Systemarchitektur, Datenfluss, Komponenten | Architektur-Fragen, "wie hängt X mit Y zusammen" |
| `docs/06_PROMPT_PATTERNS.md` | System-Prompts der Agents | Agent-Prompts bearbeiten, Prompt-Verhalten ändern |
| `docs/07_ERROR_HANDLING.md` | Bekannte Fehler und Lösungen | Bug auftritt, Fehler analysieren |
| `docs/03_ARBEITSPAKETE.md` | Definition aller APs, Anforderungen | Neues AP beginnen, "was soll AP X können" |
| `docs/08_TESTFRAGEN.md` | Testfragen für Evaluation | Testen, Evaluation durchführen |
| `docs/09_THINGSBOARD_SETUP.md` | ThingsBoard Konfiguration | ThingsBoard-Probleme, API-Fragen |
| `docs/design/[komponente].md` | Design-Entscheidungen pro Komponente | Review einer Komponente |
| `docs/DATENFLUSS.md` | Detaillierter Datenfluss | Debugging, "wo bleiben die Daten stecken" |

**Regel:** Bei Unsicherheit → **LADE DIE DATEI!** Lieber einmal zu viel als wichtige Info verpassen.

---

## ⚠️ Aktuelles Vorgehen: Architektur-Review

Wir überarbeiten das System Komponente für Komponente.

### Review-Prozess:

```
1. VERSTEHEN      → Was macht die Komponente? (Input/Output/Implementierung)
2. EINORDNEN      → Wo im Gesamtsystem? Abhängigkeiten?
3. BEWERTEN       → Was funktioniert? Was nicht? Was fehlt?
4. ALTERNATIVEN   → Optionen mit Pro/Contra (auch: andere Funktionen, weglassen?)
5. ENTSCHEIDEN    → User wählt, User begründet
6. DOKUMENTIEREN  → In docs/design/[komponente].md
7. IMPLEMENTIEREN → Nur was entschieden wurde
8. TESTEN         → Komponenten-Test + Integrations-Test
```

### Review-Status:

| Komponente | AP | Status |
|------------|-----|--------|
| ThingsBoard MCP Server | AP1 | ⏸️ **Nächste Session** |
| Data Agent | AP2 | ⏸️ Ausstehend |
| Chart MCP Server | AP3 | ⏸️ Ausstehend |
| Viz Agent | AP4 | ⏸️ Ausstehend |
| Stats Agent | AP5 | ⏸️ Ausstehend |
| Supervisor | AP6 | ⏸️ Ausstehend |

---

## 🔧 Technische Kurzreferenz

### Projektstruktur
```
conversational-analytics/
├── CLAUDE.md             # Diese Datei (Einstiegspunkt)
├── README.md             # Projekt-README
├── agents/               # Data, Viz, Stats Agent + Supervisor
├── mcp_servers/          # ThingsBoard MCP Server
├── prompts/              # System Prompts für Agents
├── evaluation/           # Testfragen und Ergebnisse
├── outputs/data/         # Gespeicherte Telemetrie-Daten
└── docs/                 # Alle Dokumentation
    ├── 02_PROJEKT_KONTEXT.md
    ├── 03_ARBEITSPAKETE.md
    ├── 04_AKTUELLER_STAND.md
    ├── 05_ARCHITEKTUR.md
    ├── 06_PROMPT_PATTERNS.md
    ├── 07_ERROR_HANDLING.md
    ├── 08_TESTFRAGEN.md
    ├── 09_THINGSBOARD_SETUP.md
    ├── 10_WOCHENPLAN.md
    └── design/           # Design-Entscheidungen
```

### Wichtige Befehle
```bash
cd ~/ma_ws/conversational-analytics
source venv/bin/activate
chainlit run app.py              # App starten
python run_tests.py              # Tests ausführen
```

### ThingsBoard
- URL: `http://localhost:8080`
- Device: KRC5 (KUKA Roboter)
- Daten: 11.12. - 16.12.2025

---

## ❌ Bekannte Probleme

1. **Daten-Limit:** >10 Keys gleichzeitig → wenige Datenpunkte pro Key
2. **Viz Agent:** Sampelt Daten manchmal unnötig
3. **"Sensordaten":** Wird manchmal als Attribute statt Telemetrie interpretiert

---

## 📝 Änderungshistorie

| Datum | Änderung |
|-------|----------|
| 19.12.2025 | Dokumentation nach docs/ verschoben, Katalog mit neuen Pfaden |
