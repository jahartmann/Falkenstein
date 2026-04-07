"""Tests for the RuleEngine message router."""

import pytest
from backend.flow.rule_engine import RuleEngine, RouteResult


@pytest.fixture
def engine():
    return RuleEngine()


# --- Quick reply: Greetings ---

def test_greeting_hallo(engine):
    assert engine.route("Hallo").action == "quick_reply"

def test_greeting_hi(engine):
    assert engine.route("hi").action == "quick_reply"

def test_greeting_hey(engine):
    assert engine.route("Hey!").action == "quick_reply"

def test_greeting_moin(engine):
    assert engine.route("moin").action == "quick_reply"

def test_greeting_guten_morgen(engine):
    assert engine.route("Guten Morgen").action == "quick_reply"

def test_greeting_guten_abend(engine):
    assert engine.route("guten abend!").action == "quick_reply"

def test_goodbye_gute_nacht(engine):
    assert engine.route("Gute Nacht").action == "quick_reply"

def test_goodbye_tschuess(engine):
    assert engine.route("tschuess").action == "quick_reply"

def test_goodbye_ciao(engine):
    assert engine.route("ciao!").action == "quick_reply"

def test_goodbye_bis_dann(engine):
    assert engine.route("Bis dann").action == "quick_reply"


# --- Quick reply: Thanks ---

def test_thanks_danke(engine):
    assert engine.route("Danke!").action == "quick_reply"

def test_thanks_vielen_dank(engine):
    assert engine.route("vielen dank").action == "quick_reply"

def test_thanks_thx(engine):
    assert engine.route("thx").action == "quick_reply"

def test_thanks_thanks(engine):
    assert engine.route("thanks").action == "quick_reply"


# --- Quick reply: Status questions ---

def test_status_was_machst_du(engine):
    assert engine.route("was machst du gerade").action == "quick_reply"

def test_status_wie_gehts(engine):
    assert engine.route("wie geht's").action == "quick_reply"

def test_status_wie_geht_es_dir(engine):
    assert engine.route("wie geht es dir").action == "quick_reply"

def test_confirmation_ok(engine):
    assert engine.route("ok").action == "quick_reply"

def test_confirmation_alles_klar(engine):
    assert engine.route("alles klar").action == "quick_reply"

def test_confirmation_passt(engine):
    assert engine.route("passt").action == "quick_reply"


# --- Crew: researcher ---

def test_crew_researcher_recherchiere(engine):
    result = engine.route("Recherchiere die besten Python Frameworks")
    assert result.action == "crew"
    assert result.crew_type == "researcher"

def test_crew_researcher_was_ist(engine):
    result = engine.route("was ist ein Transformer Modell")
    assert result.action == "crew"
    assert result.crew_type == "researcher"

def test_crew_researcher_zusammenfass(engine):
    result = engine.route("Zusammenfass diesen Artikel für mich")
    assert result.action == "crew"
    assert result.crew_type == "researcher"


# --- Crew: coder ---

def test_crew_coder_python_script(engine):
    result = engine.route("Schreib ein Python Script das Logs parsed")
    assert result.action == "crew"
    assert result.crew_type == "coder"

def test_crew_coder_code(engine):
    result = engine.route("Kannst du den Code refactoren?")
    assert result.action == "crew"
    assert result.crew_type == "coder"

def test_crew_coder_debug(engine):
    result = engine.route("debug diesen bug in meiner Funktion")
    assert result.action == "crew"
    assert result.crew_type == "coder"


# --- Crew: web_design ---

def test_crew_web_design_landing_page_tailwind(engine):
    result = engine.route("Erstell eine Landing Page mit Tailwind")
    assert result.action == "crew"
    assert result.crew_type == "web_design"

def test_crew_web_design_website(engine):
    result = engine.route("ich brauche eine Website für mein Startup")
    assert result.action == "crew"
    assert result.crew_type == "web_design"

def test_crew_web_design_html_css(engine):
    result = engine.route("html und css für ein responsives Layout")
    assert result.action == "crew"
    assert result.crew_type == "web_design"


# --- Crew: swift ---

def test_crew_swift_swiftui_ios(engine):
    result = engine.route("SwiftUI App für iOS entwickeln")
    assert result.action == "crew"
    assert result.crew_type == "swift"

def test_crew_swift_xcode(engine):
    result = engine.route("Xcode Projekt einrichten")
    assert result.action == "crew"
    assert result.crew_type == "swift"

def test_crew_swift_iphone_app(engine):
    result = engine.route("Ich möchte eine iPhone App bauen")
    assert result.action == "crew"
    assert result.crew_type == "swift"


# --- Crew: ki_expert ---

def test_crew_ki_expert_fine_tunen(engine):
    result = engine.route("Ich möchte ein Modell fine-tunen")
    assert result.action == "crew"
    assert result.crew_type == "ki_expert"

def test_crew_ki_expert_machine_learning(engine):
    result = engine.route("machine learning pipeline aufbauen")
    assert result.action == "crew"
    assert result.crew_type == "ki_expert"

def test_crew_ki_expert_embedding(engine):
    result = engine.route("embedding für RAG System erstellen")
    assert result.action == "crew"
    assert result.crew_type == "ki_expert"


# --- Crew: analyst ---

def test_crew_analyst_csv(engine):
    result = engine.route("CSV Daten analysieren und visualisieren")
    assert result.action == "crew"
    assert result.crew_type == "analyst"

def test_crew_analyst_statistik(engine):
    result = engine.route("Statistik über meine Verkaufsdaten")
    assert result.action == "crew"
    assert result.crew_type == "analyst"

def test_crew_analyst_pandas(engine):
    result = engine.route("pandas DataFrame filtern und aggregieren")
    assert result.action == "crew"
    assert result.crew_type == "analyst"


# --- Crew: ops ---

def test_crew_ops_deploy_server(engine):
    result = engine.route("Deploy Server mit Docker")
    assert result.action == "crew"
    assert result.crew_type == "ops"

def test_crew_ops_nginx(engine):
    result = engine.route("nginx Konfiguration für Reverse Proxy")
    assert result.action == "crew"
    assert result.crew_type == "ops"

def test_crew_ops_kubernetes(engine):
    result = engine.route("kubernetes k8s cluster aufsetzen")
    assert result.action == "crew"
    assert result.crew_type == "ops"


# --- Crew: writer ---

def test_crew_writer_guide(engine):
    result = engine.route("Schreib einen Guide über FastAPI")
    assert result.action == "crew"
    assert result.crew_type == "writer"

def test_crew_writer_artikel(engine):
    result = engine.route("schreib einen Artikel über KI Trends")
    assert result.action == "crew"
    assert result.crew_type == "writer"

def test_crew_writer_doku(engine):
    result = engine.route("Doku für das Projekt erstellen")
    assert result.action == "crew"
    assert result.crew_type == "writer"


# --- Classify (no match) ---

def test_classify_ambiguous(engine):
    result = engine.route("Ich überlege gerade was ich heute noch machen soll")
    assert result.action == "classify"

def test_classify_random(engine):
    result = engine.route("Erzaehl mir einen Witz")
    assert result.action == "classify"

def test_classify_empty_ish(engine):
    result = engine.route("   ")
    assert result.action == "classify"


# --- Case insensitive matching ---

def test_case_insensitive_greeting(engine):
    assert engine.route("HALLO").action == "quick_reply"

def test_case_insensitive_crew_python(engine):
    result = engine.route("PYTHON script schreiben")
    assert result.action == "crew"
    assert result.crew_type == "coder"

def test_case_insensitive_crew_swift(engine):
    result = engine.route("SWIFTUI für MACOS")
    assert result.action == "crew"
    assert result.crew_type == "swift"

def test_case_insensitive_crew_tailwind(engine):
    result = engine.route("TAILWIND CSS Layout")
    assert result.action == "crew"
    assert result.crew_type == "web_design"


# --- Priority: more specific wins over less specific ---

def test_priority_web_design_over_coder(engine):
    # "html" is web_design, "code" is coder — web_design has higher priority
    result = engine.route("html code schreiben")
    assert result.action == "crew"
    assert result.crew_type == "web_design"

def test_priority_swift_over_coder(engine):
    # "swift" is swift, "script" is coder — swift has higher priority
    result = engine.route("swift script für macos")
    assert result.action == "crew"
    assert result.crew_type == "swift"


# --- RouteResult dataclass ---

def test_route_result_quick_reply_has_no_crew_type(engine):
    result = engine.route("hi")
    assert result.crew_type is None

def test_route_result_crew_has_crew_type(engine):
    result = engine.route("python script")
    assert result.crew_type is not None

def test_route_result_classify_has_no_crew_type(engine):
    result = engine.route("etwas völlig unklares ohne keywords")
    assert result.crew_type is None
