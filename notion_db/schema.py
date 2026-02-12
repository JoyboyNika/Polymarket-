"""Schema definition for the 'Trades Suspects — Carmin' Notion database.

Contains all 29 properties organized by group:
- Vue liste (8 props)
- Détail (11 props)
- Tracking perso (4 props, Verdict shared with vue liste)
- Post-résolution (4 props)
- Technique (2 props)
"""

DATABASE_TITLE = "Trades Suspects — Carmin"

# All multi-select options for "Critères déclenchés"
CRITERES_OPTIONS = [
    "wallet_neuf",
    "mise_massive",
    "marché_improbable",
    "timing_serré",
    "compte_récent",
    "peu_tx",
    "activité_concentrée",
    "comportement_brutal",
    "financement_suspect",
    "spike_volume",
    "marché_niche",
    "mouvement_prix",
    "pattern_maduro",
    "corrélation_temporelle",
]

# Verdict select options
VERDICT_OPTIONS = [
    {"name": "🔴 Insider", "color": "red"},
    {"name": "🟡 Incertain", "color": "yellow"},
    {"name": "🟢 Faux positif", "color": "green"},
    {"name": "⬜ Non traité", "color": "default"},
    {"name": "🟠 À définir", "color": "orange"},
]

# Résultat marché select options
RESULTAT_MARCHE_OPTIONS = [
    {"name": "YES", "color": "green"},
    {"name": "NO", "color": "red"},
]


def build_properties() -> dict:
    """Build the full Notion database properties schema.

    Returns:
        dict: Properties definition compatible with Notion API create database.
    """
    properties = {}

    # ── Vue liste ──────────────────────────────────────────────
    # "Marché" is the title property (every Notion DB has exactly one)
    properties["Marché"] = {"title": {}}

    properties["Score"] = {"number": {"format": "number"}}

    properties["Montant USDC"] = {"number": {"format": "number"}}

    properties["Prix d'entrée"] = {"number": {"format": "number"}}

    properties["Multiplicateur gain"] = {
        "formula": {"expression": "1 / prop(\"Prix d'entrée\")"}
    }

    properties["Date du trade"] = {"date": {}}

    properties["Verdict"] = {
        "select": {"options": VERDICT_OPTIONS}
    }

    properties["Date alerte"] = {"created_time": {}}

    # ── Détail ─────────────────────────────────────────────────
    properties["Wallet"] = {"url": {}}

    properties["Âge du compte"] = {"rich_text": {}}

    properties["Nb transactions lifetime"] = {"number": {"format": "number"}}

    properties["Nb marchés actifs"] = {"number": {"format": "number"}}

    properties["Historique gains/pertes"] = {"rich_text": {}}

    properties["Source de financement"] = {"rich_text": {}}

    properties["Probabilité marché"] = {"number": {"format": "percent"}}

    properties["Volume marché 24h"] = {"number": {"format": "number"}}

    properties["Critères déclenchés"] = {
        "multi_select": {
            "options": [{"name": c, "color": "default"} for c in CRITERES_OPTIONS]
        }
    }

    properties["Fiche Haiku"] = {"rich_text": {}}

    properties["Prédiction ML"] = {"rich_text": {}}

    # ── Tracking perso ─────────────────────────────────────────
    # Verdict already defined above (shared property)

    properties["Raison du verdict"] = {"rich_text": {}}

    properties["Notes perso / Deep Search"] = {"rich_text": {}}

    properties["Trade pris"] = {"checkbox": {}}

    properties["Somme misée"] = {"number": {"format": "number"}}

    # ── Post-résolution ────────────────────────────────────────
    properties["Date fin marché"] = {"date": {}}

    properties["Résultat marché"] = {
        "select": {"options": RESULTAT_MARCHE_OPTIONS}
    }

    properties["Trade suspect réussi"] = {"checkbox": {}}

    properties["Gain réel suspect"] = {"number": {"format": "number"}}

    # ── Technique (ajoutées par l'audit) ───────────────────────
    properties["Condition ID marché"] = {"rich_text": {}}

    properties["Trade ID"] = {"rich_text": {}}

    return properties
