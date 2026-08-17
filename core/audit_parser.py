"""
Extraction par règles (regex) d'un audit énergétique réglementaire PDF — sans IA.

Principe :
- pdfplumber donne la position (x, y) de chaque caractère de façon fiable, même quand
  l'ordre du flux PDF est scramblé (cas fréquent des pastilles CEP/étiquette dessinées
  caractère par caractère). On reconstruit donc le texte ligne par ligne en triant les
  caractères par position plutôt qu'en utilisant l'extraction brute.
- Le texte reconstruit est ensuite parsé avec un jeu de regex couvrant les formulations
  observées dans les audits (logiciels LICIEL / Climawin et probablement proches, la
  structure réglementaire étant imposée par l'arrêté du 4 mai 2022).

Limites connues (assumées) :
- L'étiquette (lettre A à G) des pastilles est parfois un dessin vectoriel non
  extractible en texte : on tente une récupération via les phrases du type
  "atteindre la lettre A" quand elles existent, sinon le champ reste vide.
- Le repérage des postes de travaux (Murs / Plancher / Toiture / Menuiseries /
  Ventilation / Chauffage / ECS) repose sur des mots-clés d'en-tête ; un logiciel
  d'audit qui utiliserait une terminologie totalement différente ne sera pas couvert
  sans ajustement des motifs ci-dessous.
- => Toujours relire/corriger le résultat dans l'interface avant de générer l'Excel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber

# ---------------------------------------------------------------------------
# Reconstruction du texte par position
# ---------------------------------------------------------------------------

def reflow_page_text(page, y_tol: float = 3.0, x_gap: float = 2.0) -> str:
    """Reconstruit le texte d'une page en triant les caractères par (y, x)
    plutôt qu'en suivant l'ordre du flux PDF (corrige le scramble des pastilles)."""
    chars = page.chars
    lines: dict[float, list] = {}
    for c in chars:
        key = round(c["top"] / y_tol) * y_tol
        lines.setdefault(key, []).append(c)

    out = []
    for k in sorted(lines.keys()):
        row = sorted(lines[k], key=lambda c: c["x0"])
        s, prev_x1 = "", None
        for c in row:
            if prev_x1 is not None and c["x0"] - prev_x1 > x_gap:
                s += " "
            s += c["text"]
            prev_x1 = c["x1"]
        out.append(s.rstrip())
    return "\n".join(out)


def reflow_pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(pdf_bytes if hasattr(pdf_bytes, "read") else _bytes_io(pdf_bytes)) as pdf:
        return "\n".join(reflow_page_text(p) for p in pdf.pages)


def _bytes_io(b: bytes):
    import io
    return io.BytesIO(b)


# ---------------------------------------------------------------------------
# Regex génériques
# ---------------------------------------------------------------------------

RE_ADRESSE = re.compile(r"Adresse\s*:\s*(.+?)(?:\n\s*\n|\nType de bien|\nPropri)", re.S)
RE_BENEFICIAIRE = re.compile(r"(?:Propri[ée]taire|Commanditaire)\s*:\s*(.+)")
RE_SURFACE = re.compile(r"Surface de r[ée]f[ée]rence\s*:\s*([\d\s.,]+)\s*m")
RE_NB_LOGEMENTS = re.compile(r"Nombre de logements\s*:?\s*(\d+)")
RE_DATE_VISITE = re.compile(r"Date de visite\s*:?\s*(\d{2}/\d{2}/\d{4})")

# Total EP/EF — deux mises en forme rencontrées selon le logiciel d'audit :
#   LICIEL   : "(kWh/m²/an)" puis "222  (96 )" puis "EP EF" sur la ligne suivante
#   Climawin : "(kWh EP/m²/an)" puis "95 ep" puis "(88 ef)" sur la ligne suivante
RE_TOTAL_EP_EF_LICIEL = re.compile(
    r"\(\s*kWh\s*/\s*m[²2]\s*/\s*an\s*\)\s*\n(?:[^\n]*\n){0,3}?\s*(\d[\d\s]*)\s*\(\s*(\d[\d\s]*)\s*\)\s*\n\s*EP\s*EF",
    re.I,
)
RE_TOTAL_EP_EF_CLIMAWIN = re.compile(
    r"(\d[\d\s]*)\s*ep\s*\n\s*\(\s*(\d[\d\s]*)\s*ef\s*\)",
    re.I,
)


def find_total_ep_ef(block: str):
    m = RE_TOTAL_EP_EF_LICIEL.search(block)
    if m:
        return m
    return RE_TOTAL_EP_EF_CLIMAWIN.search(block)

# Deux formats rencontrés :
#  - "Scénario 1 « rénovation en une fois »" (numéroté)
#  - "Scénario de travaux en une étape «rénovation en une fois»" (non numéroté)
RE_SCENARIO_HEADER = re.compile(
    r"Sc[ée]nario\s*(\d)?\s*(?:de travaux\s*(?:en\s+(?:une|plusieurs)\s+[ée]tapes?)?)?\s*«\s*([^»]+)\s*»",
    re.I,
)
RE_ETAPE_HEADER = re.compile(
    r"^(Premi[èe]re|Deuxi[èe]me|Derni[èe]re|Seule)\s+[ée]tape", re.I | re.M
)
RE_PCT_ECONOMIE = re.compile(r"-\s*(\d{1,3})\s*%")
RE_COUT = re.compile(r"≈?\s*([\d][\d\s]{1,9})\s*€")
RE_LETTRE_EXPLICITE = re.compile(r"lettre\s+([A-G])\b")

# Un même titre de scénario apparaît plusieurs fois dans un audit (sommaire p.1, tableau
# "en un clin d'œil", puis la ou les vraies pages de détail). On ne garde que les
# occurrences suivies de peu par un marqueur propre aux pages de détail.
RE_REAL_PAGE_MARKER = re.compile(
    r"(aides financi[èe]res possibles|D[ée]tail[s]? des travaux|R[ée]sultats apr[èe]s travaux)",
    re.I,
)

# En-têtes de postes de travaux (les deux formats rencontrés : LICIEL et Climawin)
POSTE_KEYWORDS = [
    ("Murs?", "Murs"),
    ("Plancher[s]?\\s*bas", "Planchers bas"),
    ("Plancher(?!s)", "Plancher"),
    ("Toiture", "Toiture / Combles"),
    ("Menuiserie", "Menuiseries"),
    ("Portes? et fen[êe]tres", "Menuiseries"),
    ("Syst[èe]me de ventilation", "Ventilation"),
    ("Ventilation", "Ventilation"),
    ("Syst[èe]me de chauffage", "Chauffage"),
    ("Chauffage", "Chauffage"),
    ("ECS", "Eau chaude sanitaire"),
]
RE_POSTE_HEADER = re.compile(
    r"^((?:" + "|".join(p for p, _ in POSTE_KEYWORDS) + r")[^\n]*)$",
    re.M,
)

# ---------------------------------------------------------------------------
# Étiquette DPE calculée à partir du CEP (arrêté du 8 octobre 2021, seuils énergie
# primaire — la note GES n'est pas exploitée ici : en cas de doute, la lettre
# explicitement écrite dans le document ("atteindre la lettre X") prime toujours).
# ---------------------------------------------------------------------------

CEP_THRESHOLDS = [(70, "A"), (110, "B"), (180, "C"), (250, "D"), (330, "E"), (420, "F")]


def cep_to_etiquette(cep: float | None) -> str | None:
    if cep is None:
        return None
    for seuil, lettre in CEP_THRESHOLDS:
        if cep <= seuil:
            return lettre
    return "G"


# ---------------------------------------------------------------------------
# Extraction ciblée des caractéristiques techniques / surface / quantité dans la
# description d'un poste de travaux (mots-clés, sans IA).
# ---------------------------------------------------------------------------

SPEC_SPECS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:R\s*(?:>=|>|=|≥)|[Rr]ésistance\s+thermique[^\n.]{0,40}?(?:>=|>|=|≥))\s*([\d,.]+)\s*m[²2]\.?\s*K\s*/\s*W"), "R ≥ {0} m².K/W"),
    (re.compile(r"Th\s*(\d+)(?:\s+(\d+)\s*mm)?", re.I), None),  # géré à part (2 groupes optionnels)
    (re.compile(r"SCOP\s*(?:>=|>|=)?\s*([\d,.]+)", re.I), "SCOP ≥ {0}"),
    (re.compile(r"Uw?\s*(?:>=|>|=|≥)?\s*([\d,.]+)\s*W\s*/\s*m[²2]\.?\s*K", re.I), "Uw = {0} W/m².K"),
    (re.compile(r"Sw\s*(?:>=|>|=)?\s*([\d,.]+)", re.I), "Sw = {0}"),
    (re.compile(r"[ée]paisseur[^\n.]{0,20}?([\d,.]+)\s*(mm|cm)", re.I), "Épaisseur {0}{1}"),
    (re.compile(r"contenance[^\n.]{0,20}?([\d,.]+)\s*L\b", re.I), "Ballon {0}L"),
    (re.compile(r"Ud\s*=?\s*([\d,.]+)\s*W\s*/\s*m[²2]\.?\s*K", re.I), "Ud = {0} W/m².K"),
]

RE_QTY_SURFACE = re.compile(r"[Ss]urface\s+concern[ée]e?\s*=?\s*\[?([\d,.]+)\]?\s*m[²2]")
RE_QTY_SURFACE_FALLBACK = re.compile(r"([\d,.]+)\s*m[²2](?!\.?\s*K\s*/\s*W)\b")
RE_QTY_UNITE = re.compile(r"\b(\d+)\s*(?:u\.|unit[ée]s?)\b", re.I)

# Un montant en euros s'insère parfois au milieu d'une phrase après la reconstruction
# x/y (colonne "coût" adjacente au texte) : on le retire avant toute analyse de texte.
RE_PRICE_INLINE = re.compile(r"[\d][\d\s]{0,9}\s*€")


def _clean_for_parsing(text: str) -> str:
    text = RE_PRICE_INLINE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_specs(text: str) -> str:
    text = _clean_for_parsing(text)
    parts: list[str] = []
    for rex, template in SPEC_SPECS:
        m = rex.search(text)
        if not m:
            continue
        if template is None:  # cas "Th35 130 mm"
            val = f"Th{m.group(1)}" + (f" {m.group(2)}mm" if m.group(2) else "")
        else:
            val = template.format(*m.groups())
        if val not in parts:
            parts.append(val)
    return " ; ".join(parts)


def _extract_quantite(text: str) -> str:
    text = _clean_for_parsing(text)
    m = RE_QTY_SURFACE.search(text)
    if m:
        return f"{m.group(1)} m²"
    m = RE_QTY_SURFACE_FALLBACK.search(text)
    if m:
        return f"{m.group(1)} m²"
    m = RE_QTY_UNITE.search(text)
    if m:
        return f"{m.group(1)} u."
    return ""


def _first_sentence(text: str) -> str:
    """Première phrase, sans se faire piéger par un point décimal (ex. "SCOP >= 4.6")."""
    text = _clean_for_parsing(text)
    i = 0
    while True:
        idx = text.find(".", i)
        if idx == -1:
            return text[:150].strip()
        before = text[idx - 1] if idx > 0 else ""
        after = text[idx + 1] if idx + 1 < len(text) else ""
        if before.isdigit() and after.isdigit():
            i = idx + 1
            continue
        return text[: idx + 1].strip()


def _num(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace("\u202f", " ").replace(",", ".")
    s = re.sub(r"\s+", "", s)
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------

@dataclass
class Travail:
    poste: str
    nature_courte: str        # ex. "Isolation des murs périphériques par l'extérieur."
    caracteristiques: str      # ex. "R >= 4,4 m².K/W ; Th35 130 mm"
    quantite: str              # ex. "173.35 m²"
    description: str = ""      # texte brut complet (référence / debug)
    cout_ttc: float | None = None

    @property
    def nature_affichee(self) -> str:
        """Colonne "Nature des travaux" : poste + phrase courte entre parenthèses."""
        if self.nature_courte:
            return f"{self.poste} ({self.nature_courte})"
        return self.poste


@dataclass
class Etape:
    libelle: str
    cep_apres: float | None = None
    cef_apres: float | None = None
    economie_pct: float | None = None
    etiquette_apres: str | None = None
    cout_travaux_ttc: float | None = None
    travaux: list[Travail] = field(default_factory=list)


@dataclass
class Scenario:
    id: str
    nom: str
    etapes: list[Etape] = field(default_factory=list)

    @property
    def cout_total(self) -> float | None:
        couts = [e.cout_travaux_ttc for e in self.etapes if e.cout_travaux_ttc]
        return sum(couts) if couts else None


@dataclass
class Batiment:
    adresse: str | None = None
    beneficiaire: str | None = None
    surface_m2: float | None = None
    nb_logements: int | None = None
    date_visite: str | None = None
    cep_initial: float | None = None
    cef_initial: float | None = None
    etiquette_initiale: str | None = None


# ---------------------------------------------------------------------------
# Parsing bâtiment
# ---------------------------------------------------------------------------

def parse_batiment(text: str) -> Batiment:
    b = Batiment()
    m = RE_ADRESSE.search(text)
    if m:
        b.adresse = re.sub(r"\s+", " ", m.group(1)).strip()
    m = RE_BENEFICIAIRE.search(text)
    if m:
        b.beneficiaire = m.group(1).strip()
    m = RE_SURFACE.search(text)
    if m:
        b.surface_m2 = _num(m.group(1))
    m = RE_NB_LOGEMENTS.search(text)
    if m:
        b.nb_logements = int(m.group(1))
    m = RE_DATE_VISITE.search(text)
    if m:
        b.date_visite = m.group(1)

    # premier total EP/EF rencontré dans le document (page "Montants et consommations
    # annuels d'énergie") = état initial
    idx = text.lower().find("ontants et consommations annuels d")
    m = find_total_ep_ef(text[idx:] if idx != -1 else text)
    if m:
        b.cep_initial = _num(m.group(1))
        b.cef_initial = _num(m.group(2))

    # étiquette : lettre explicite si trouvée, sinon calculée depuis le CEP
    m = RE_LETTRE_EXPLICITE.search(text[: idx if idx != -1 else 3000])
    b.etiquette_initiale = m.group(1) if m else cep_to_etiquette(b.cep_initial)

    return b


# ---------------------------------------------------------------------------
# Parsing des postes de travaux dans un bloc "Détail des travaux énergétiques"
# ---------------------------------------------------------------------------

def parse_travaux_block(block: str) -> list[Travail]:
    headers = list(RE_POSTE_HEADER.finditer(block))
    travaux: list[Travail] = []
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(block)
        chunk = block[start:end].strip()

        header_line = m.group(1).strip()
        poste_label = header_line
        for pattern, label in POSTE_KEYWORDS:
            if re.match(pattern, header_line, re.I):
                poste_label = label
                break

        couts = RE_COUT.findall(chunk)
        cout = _num(couts[-1]) if couts else None
        description = re.sub(r"\s+", " ", chunk).strip()

        travaux.append(
            Travail(
                poste=poste_label,
                nature_courte=_first_sentence(description),
                caracteristiques=_extract_specs(description),
                quantite=_extract_quantite(description),
                description=description[:600],
                cout_ttc=cout,
            )
        )
    return travaux


# ---------------------------------------------------------------------------
# Parsing des scénarios
# ---------------------------------------------------------------------------

def _normalize_titre(titre: str) -> str:
    return re.sub(r"\s+", " ", titre).strip().lower()


def parse_scenarios(text: str) -> list[Scenario]:
    """Repère les en-têtes de scénario, ignore le sommaire 'clin d'œil' (qui les cite
    tous une première fois en haut du document), et fusionne les en-têtes répétés d'un
    même scénario qui réapparaissent en haut de chaque page (cas Climawin)."""

    all_headers = list(RE_SCENARIO_HEADER.finditer(text))

    # Le sommaire (p.1) et le tableau "en un clin d'œil" citent tous les titres de
    # scénario sans être de vraies pages de détail : on ne garde qu'une occurrence si
    # elle est suivie de peu par un marqueur propre aux pages de détail.
    headers = [
        m for m in all_headers
        if RE_REAL_PAGE_MARKER.search(text[m.end() : m.end() + 250])
    ]
    if not headers:  # filet de sécurité si aucun marqueur ne matche
        headers = all_headers

    # Fusionne les occurrences consécutives de même titre (même scénario réétalé sur
    # plusieurs pages, chacune reprenant l'en-tête).
    groups: list[list] = []
    for m in headers:
        key = (m.group(1), _normalize_titre(m.group(2)))
        if groups and groups[-1][0] == key:
            groups[-1][1].append(m)
        else:
            groups.append([key, [m]])

    scenarios: list[Scenario] = []
    for idx, ((num, _), matches) in enumerate(groups, start=1):
        first, last = matches[0], matches[-1]
        titre = first.group(2).strip()
        start = first.end()
        end = groups[idx][1][0].start() if idx < len(groups) else len(text)
        block = text[start:end]

        label_num = num or str(idx)
        sc = Scenario(id=f"scenario_{label_num}", nom=f"Scénario {label_num} « {titre} »")

        etape_headers = list(RE_ETAPE_HEADER.finditer(block))
        if not etape_headers:
            sc.etapes.append(_parse_etape("Étape unique", block))
        else:
            for j, em in enumerate(etape_headers):
                estart = em.start()
                eend = etape_headers[j + 1].start() if j + 1 < len(etape_headers) else len(block)
                sc.etapes.append(_parse_etape(em.group(0).strip(), block[estart:eend]))

        scenarios.append(sc)

    return scenarios


def _parse_etape(libelle: str, block: str) -> Etape:
    e = Etape(libelle=libelle)

    # La section réglementaire "Résultats après travaux" (présente sur les deux logiciels
    # testés) regroupe économies %, CEP/CEF finaux et coût total : on cible cette fenêtre
    # en priorité pour éviter de récupérer une valeur d'une autre étape du même bloc.
    ridx = block.lower().find("ésultats après travaux")
    window = block[ridx : ridx + 1500] if ridx != -1 else block

    m = RE_PCT_ECONOMIE.search(window)
    if m:
        e.economie_pct = _num(m.group(1))

    m = find_total_ep_ef(window)
    if m:
        e.cep_apres = _num(m.group(1))
        e.cef_apres = _num(m.group(2))

    m = RE_LETTRE_EXPLICITE.search(block)
    e.etiquette_apres = m.group(1) if m else cep_to_etiquette(e.cep_apres)

    couts = RE_COUT.findall(window)
    if couts:
        e.cout_travaux_ttc = _num(couts[-1])

    # détail des postes de travaux
    det_start = block.find("Détail des travaux énergétiques")
    if det_start == -1:
        det_start = block.find("étails des travaux énergétiques")
    if det_start != -1:
        det_end = block.find("Détail des travaux induits", det_start)
        if det_end == -1:
            det_end = block.find("Résultats après travaux", det_start)
        if det_end == -1:
            det_end = len(block)
        e.travaux = parse_travaux_block(block[det_start:det_end])

    return e


# ---------------------------------------------------------------------------
# API principale
# ---------------------------------------------------------------------------

def parse_audit_pdf(pdf_bytes: bytes) -> tuple[Batiment, list[Scenario]]:
    text = reflow_pdf_text(pdf_bytes)
    batiment = parse_batiment(text)
    scenarios = parse_scenarios(text)
    return batiment, scenarios
