"""
Motifs CEE repérés automatiquement dans les PDF OCRisés (page 5_Recherche_OCR).
Sources : méthode d'instruction + « Règles par type de document » + « Règles techniques ».

Trois blocs :
  1. ADMINISTRATIF : motifs par catégorie (identification, lien fort, pièces, signatures, RGE, AH)
  2. ELEMENTS      : éléments techniques génériques (R, Uw, ETAS…), réutilisés par les fiches
  3. FICHES        : par fiche BAR → termes de détection + checklist des éléments attendus

Motif administratif / élément :
    regex     : expression régulière (c'est le match complet qui est affiché)
    casse     : True = sensible à la casse (par défaut : insensible)
    presence  : True = signalé ❌ s'il est absent (administratif uniquement)
    partout   : True = cherché dans tout le document, pas seulement sur les pages de la fiche
                (document séparé : certificat RGE, ACERMI, tableau de répartition…)
    surligner : False = repéré dans les tableaux mais pas surligné dans le PDF (ex. montants)
    note      : aide (optionnel)

Les regex tolèrent les espaces et tirets parasites de l'OCR.
"""
import re
from functools import lru_cache

MOIS = r"(?:janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[ée]c)\w*\.?"
APOS = r"['’]?\s?"
OEUVRE = r"(?:oe|œ)uvre"
NUM = r"\s*(?:n\s?[°o]?|num[ée]ro|r[ée]f[ée]rence|r[ée]f\.?)\s*:?\s*"  # « n° » (° souvent perdu à l'OCR), « numéro », « réf. »…
DATE = r"\d{1,2}\s?([/.-])\s?\d{1,2}\s?\1\s?(?:\d{4}|\d{2})"

CODE_FICHE = r"\bBA[RT]\s?[-–]?\s?(?:EN|TH|EQ|SE)\s?[-–]?\s?\d{3}\b"


def _libelles(*textes):
    """Libellés exacts → regex tolérante (espaces multiples, apostrophes, accents perdus à l'OCR)."""
    alts = []
    for t in textes:
        rx = re.escape(t).replace(r"\ ", " ").replace(" ", r"\s+")
        rx = rx.replace("'", "['’]").replace("é", "[ée]").replace("è", "[èe]").replace("ê", "[êe]")
        alts.append(rx)
    return r"\b(?:" + "|".join(alts) + r")\b"


def normaliser_code(code):
    """'bar th 171' → 'BAR-TH-171'."""
    m = re.match(r"(BA[RT])\W*([A-Z]{2})\W*(\d{3})", code.upper())
    return f"{m[1]}-{m[2]}-{m[3]}" if m else code.upper()


# =====================================================================
# 1. ADMINISTRATIF
# =====================================================================
ADMINISTRATIF = {
    "Identification": [
        {"nom": "Code fiche", "presence": True, "regex": CODE_FICHE},
        {"nom": "SIRET", "presence": True,
         "regex": r"\b\d{3}\s?\d{3}\s?\d{3}\s?\d{5}\b",
         "note": "Validation RGE obligatoirement au SIRET (le SIREN seul ne suffit pas)"},
        {"nom": "SIREN (après le mot SIREN)",
         "regex": r"\bSIREN\s*:?\s*\d{3}\s?\d{3}\s?\d{3}\b"},
        {"nom": "TVA intracommunautaire",
         "regex": r"\bFR\s?[0-9A-Z]{2}\s?\d{3}\s?\d{3}\s?\d{3}\b"},
        {"nom": "N° dossier ODICEE",
         "regex": r"\bODICEE\b[^\n]{0,25}?\d[\w/-]{3,}"},
        {"nom": "Demande de VISA", "regex": r"\bdemande\s+de\s+visa\b"},
    ],
    "Lien fort (adresse / marché / lot)": [
        {"nom": "Adresse (n° + voie)", "presence": True,
         "regex": r"\b\d{1,4}\s?(?:bis|ter)?,?\s+(?:rue|av(?:enue)?\.?|bd|boulevard|chemin|all[ée]e|impasse"
                  r"|place|route|quai|cours|r[ée]sidence|square|lotissement)\b(?:\s+[^\d\s]+){1,4}"},
        {"nom": "Code postal + ville", "casse": True,
         "regex": r"(?<![\w-])(?:0[1-9]|[1-8]\d|9[0-5]|2[AB])\d{3}\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’]+(?:-[A-Za-zÀ-ÿ'’]+)*"},
        {"nom": "Résidence / lieu des travaux",
         "regex": r"\b(?:r[ée]sidence|cit[ée]|groupe|ensemble\s+immobilier|b[âa]timent|b[âa]t\.)\s+[^\d\s]+(?:\s+[^\d\s]+){0,3}"},
        {"nom": "N° de marché", "presence": True,
         "regex": rf"\bmarch[ée]{NUM}[\w/.-]*\d[\w/.-]*",
         "note": "Si préfixe alphabétique, seuls les chiffres sont à comparer"},
        {"nom": "N° de commande", "regex": rf"\b(?:commande|BC){NUM}[\w/.-]*\d[\w/.-]*"},
        {"nom": "N° de lot", "presence": True, "regex": r"\blot\s*(?:n\s?[°o]?)?\s*:?\s*\d{1,3}\b"},
        {"nom": "Objet du marché / opération",
         "regex": r"\b(?:objet\s+du\s+march[ée]|objet\s+des\s+travaux|nom\s+de\s+l['’]?\s?op[ée]ration|op[ée]ration\s*:)"},
    ],
    "Pièces engagement / réalisation": [
        {"nom": "Devis", "regex": r"\bdevis\b"},
        {"nom": "N° de devis", "regex": rf"\bdevis{NUM}[\w/.-]*\d[\w/.-]*"},
        {"nom": "Validité du devis",
         "regex": r"\b(?:valable|validit[ée]\s+(?:du\s+devis|de\s+l['’]?\s?offre)|dur[ée]e\s+de\s+validit[ée])\b"},
        {"nom": "Acte d'engagement", "regex": rf"\bacte\s+d{APOS}engagement\b"},
        {"nom": "Ordre de service", "regex": r"\bordre\s+de\s+service\b"},
        {"nom": "N° d'OS", "regex": r"\b(?:OS|ordre\s+de\s+service)\s*(?:n[°o])?\s*:?\s*\d{1,3}\b",
         "note": "Seul l'OS n°1 vaut engagement"},
        {"nom": "Bon / lettre de commande ou de travaux",
         "regex": r"\b(?:bon|lettre)\s+de\s+(?:commande|travaux)\b"},
        {"nom": "Démarrage / préparation des travaux",
         "regex": r"\b(?:d[ée]marrage|commencement|d[ée]but|pr[ée]paration)\s+des\s+travaux\b"},
        {"nom": "Facture", "regex": r"\bfacture\b"},
        {"nom": "N° de facture", "regex": rf"\bfacture{NUM}[\w/.-]*\d[\w/.-]*"},
        {"nom": "Situation / avancement",
         "regex": r"\b(?:situation(?:\s+de\s+travaux)?(?:\s*n[°o]?\s?\d+)?|avancement)\b"},
        {"nom": "DGD",
         "regex": r"\b(?:DGD|d[ée]compte\s+g[ée]n[ée]ral(?:\s+(?:et\s+)?d[ée]finitif)?)\b"},
        {"nom": "DPGF",
         "regex": r"\b(?:DPGF|d[ée]composition\s+du\s+prix\s+global\s+et\s+forfaitaire)\b"},
        {"nom": "PV de réception",
         "regex": r"\b(?:PV|proc[èe]s[- ]?verbal)\s+de\s+r[ée]ception\b"},
        {"nom": "Réception avec / sans réserves",
         "regex": r"\b(?:sans|avec)\s+r[ée]serves?\b"},
        {"nom": "PV de levée des réserves",
         "regex": r"\b(?:(?:PV|proc[èe]s[- ]?verbal)\s+de\s+)?lev[ée]e\s+des\s+r[ée]serves\b"},
        {"nom": "Avenant", "regex": r"\bavenant\b"},
    ],
    "Dates et montants": [
        {"nom": "Date (numérique)", "regex": rf"\b{DATE}\b"},
        {"nom": "Date (en lettres)", "regex": rf"\b\d{{1,2}}(?:er)?\s+{MOIS}\s+\d{{4}}\b"},
        {"nom": "Mois + année seuls", "regex": rf"\b(?<!\d\s){MOIS}\s+\d{{4}}\b",
         "note": "Date sans jour : on retient le dernier jour du mois"},
        {"nom": "Total HT", "presence": True, "surligner": False,
         "regex": r"\b(?:total|montant)\s+(?:g[ée]n[ée]ral\s+)?(?:HT|hors\s+taxes?)\b[^\n]{0,20}?\d[\d . ]*,\d{2}",
         "note": "Lien fort : tolérance 0,01 €"},
        {"nom": "Montant (€)", "surligner": False, "regex": r"\b\d{1,3}(?:[ . ]?\d{3})*,\d{2}\s?(?:€|EUR)"},
        {"nom": "Avancement 100 %", "regex": r"\b100\s?%"},
    ],
    "Signatures / parties": [
        {"nom": "Maîtrise d'ouvrage (MOA)", "presence": True,
         "regex": rf"\b(?:ma[îi]tr(?:e|ise)\s+d{APOS}ouvrage|MOA)\b"},
        {"nom": "Maîtrise d'œuvre (MOE)", "regex": rf"\b(?:ma[îi]tr(?:e|ise)\s+d{APOS}{OEUVRE}|MOE)\b"},
        {"nom": "Titulaire / co-traitant", "regex": r"\b(?:titulaire|co[- ]?traitant|mandataire)\b"},
        {"nom": "Signature / bon pour accord", "presence": True,
         "regex": r"\b(?:signature|sign[ée]|bon\s+pour\s+accord|lu\s+et\s+approuv[ée])\b"},
        {"nom": "Signature électronique",
         "regex": r"\b(?:signature\s+[ée]lectronique|sign[ée]\s+[ée]lectroniquement|docusign|yousign|universign)\b",
         "note": "Si valide : nom, prénom et fonction du signataire non nécessaires"},
        {"nom": "Cachet / tampon", "regex": r"\b(?:cachet|tampon)\b"},
        {"nom": "Nom / fonction du signataire",
         "regex": r"\b(?:qualit[ée]|fonction|nom|pr[ée]nom)\s+du\s+signataire\b"},
    ],
    "RGE / sous-traitance": [
        {"nom": "Organisme RGE", "presence": True,
         "regex": r"\b(?:RGE|Qualibat|Qualifelec|QualiPAC|Quali['’]?EnR|Qualibois|QualiSol|Eurovent|Certibat)\b"},
        {"nom": "N° de qualification / certification",
         "regex": r"\b(?:qualification|certificat(?:ion)?|num[ée]ro\s+client|n[°o]\s+client)\s*(?:n[°o])?\s*:?\s*[A-Z]{0,3}-?[A-Z]?\s?\d{4,8}\b",
         "note": "Qualifelec : le « numéro client » sert de n° de certification"},
        {"nom": "N° Qualibat (à valider)", "casse": True, "regex": r"\bE-?E?\s?\d{5,7}\b"},
        {"nom": "Date d'attribution / validité",
         "regex": r"\b(?:date\s+d['’]?\s?attribution|attribu[ée]e?\s+le|valable\s+(?:du|jusqu)|valide\s+jusqu|p[ée]riode\s+de\s+validit[ée]|date\s+d['’]?\s?(?:expiration|[ée]ch[ée]ance))\b"},
        {"nom": "Sous-traitance", "presence": True, "regex": r"\bsous[- ]?trait\w*\b"},
        {"nom": "Déclaration de sous-traitance (DC4)",
         "regex": r"\b(?:d[ée]claration\s+de\s+sous[- ]?traitance|DC\s?4)\b"},
    ],
    "Attestation sur l'honneur": [
        {"nom": "Attestation sur l'honneur", "presence": True,
         "regex": rf"\battestation\s+sur\s+l{APOS}honneur\b"},
        {"nom": "Partie A (A, A1…An)", "casse": True, "regex": r"(?:^|\s)A\d{0,2}\s?[/.)]\s"},
        {"nom": "Partie B – Bénéficiaire",
         "regex": r"\bB\s?[/.)]?\s*b[ée]n[ée]ficiaire\s+de\s+l['’]?\s?op[ée]ration\b"},
        {"nom": "Partie C – Professionnel / MOE",
         "regex": rf"\bC\s?[/.)]?\s*professionnel\s+ayant\s+mis\s+en\s+{OEUVRE}\b"},
        {"nom": "Partie BS – Bailleur social", "regex": r"\bBS\s?[/.)]?\s*bailleur\s+social\b"},
        {"nom": "Nombre total de ménages", "regex": r"\bnombre\s+total\s+de\s+m[ée]nages\b[^\n]{0,15}?\d*"},
        {"nom": "Ménages en logement conventionné", "regex": r"\blogements?\s+conventionn[ée]s?\b"},
        {"nom": "Pagination (page x/y)", "regex": r"\b(?:page|p\.)\s*\d{1,3}\s*(?:/|sur)\s*\d{1,3}\b"},
    ],
}
MOTIFS = ADMINISTRATIF  # compatibilité

# Lignes de synthèse : présent si au moins une des pièces listées est trouvée
PREUVES = {
    "Preuve d'engagement (devis, AE, OS, BC)":
        ["Devis", "Acte d'engagement", "Ordre de service", "Bon / lettre de commande ou de travaux"],
    "Preuve de réalisation (facture, DGD, PV)": ["Facture", "DGD", "PV de réception"],
}


# =====================================================================
# 2. ÉLÉMENTS TECHNIQUES (génériques)
# =====================================================================
ELEMENTS = {
    "Surface (m²)": {"regex": r"\b\d+(?:[ .]\d{3})*(?:[.,]\d+)?\s?m[²2](?![\s.·/]*K)"},
    "Résistance thermique R": {
        "regex": r"\bR\s?[=:]\s?\d{1,2}[.,]\d{1,2}(?:\s?m[²2]\s?[.·]?\s?K\s?/\s?W)?"
                 r"|\b\d{1,2}[.,]\d{1,2}\s?m[²2]\s?[.·/]?\s?K\s?/\s?W"},
    "Épaisseur (mm)": {"regex": r"\b(?:[ée]p(?:aisseur)?\.?\s*:?\s*)?\d{2,3}\s?mm\b"},
    "Date de visite préalable": {
        "regex": rf"\bvisite\s+pr[ée]alable\b(?:[^\n]{{0,30}}?{DATE})?",
        "note": "Obligatoire selon la version de fiche (EN-101/102 : 2018-2022 ; EN-103 : 2019)"},
    "Certificat ACERMI": {
        "regex": r"\bACERMI\b(?:[^\n]{0,15}?\d{2}\s?/\s?\d{3}\s?/\s?\d{3,4})?", "partout": True,
        "note": "À lire si marque et référence de l'isolant sont sur la preuve de réalisation"},
    "Tableau de répartition": {
        "regex": r"\btableau\s+de\s+r[ée]partition\b|\br[ée]partition\s+des\s+surfaces\b", "partout": True,
        "note": "Si plusieurs accès / bâtiments : total = quantitatif facturé"},
    "Quantité (u)": {"regex": r"\b\d+\s?(?:u|U|unit[ée]s?|ens\.?)\b"},
    "Uw": {"regex": r"\bUw\s?[=:]?\s?\d[.,]\d{1,2}"},
    "Sw": {"regex": r"\bSw\s?[=:]?\s?\d[.,]\d{1,2}"},
    "Puissance (W / kW)": {"regex": r"(?<![/.])\b\d+(?:[.,]\d+)?\s?k?W\b(?!\s?h)"},
    "ETAS (%)": {
        "regex": r"\b(?:[ée]tas|efficacit[ée]\s+[ée]nerg[ée]tique\s+saisonni[èe]re)\b[^\n]{0,30}?\d{2,3}\s?%"},
    "Classe du régulateur": {"regex": r"\bclasse\s+(?:VIII|VII|VI|IV|V|III|II|I|[1-8])\b"},
    "Surface habitable": {
        "regex": r"\bsurface\s+habitable\b(?:[^\n]{0,20}?\d+(?:[.,]\d+)?\s?m[²2])?"},
    "Mention « basse température »": {"regex": r"\bbasse\s+temp[ée]rature\b"},
    "Hygroréglable type A / B": {"regex": r"\bhygro(?:r[ée]glable)?\b(?:\s*(?:de\s+)?type\s*[AB]\b|\s+[AB]\b)?"},
    "Puissance absorbée pondérée (WThC/m³/h)": {
        "regex": r"\b\d+(?:[.,]\d+)?\s?W\s?-?\s?Th\s?-?\s?C\s?/\s?m[3³]\s?/\s?h\b"},
    "ATec / DTA": {
        "regex": r"\b(?:ATec|Avis\s+Technique|DTA)\b[^\n]{0,20}?\d{1,2}(?:\.\d)?\s?/\s?\d{2}\s?-\s?\d{3,4}(?:_V\d)?"},
    "Mention NF 3 étoiles œil": {"regex": r"\bNF\b[^\n]{0,40}?(?:3\s?\*|3\s?[ée]toiles?|(?:oe|œ)il)"},
}

ISOLATION = ["Surface (m²)", "Résistance thermique R", "Épaisseur (mm)", "Date de visite préalable",
             "Marque de l'isolant", "Référence de l'isolant", "Certificat ACERMI", "Tableau de répartition"]


# =====================================================================
# 3. FICHES : termes de détection + checklist (d'après « Rapport éléments techniques »)
#    Un élément absent de ELEMENTS (marque, référence…) apparaît en « 👁️ À vérifier ».
# =====================================================================
FICHES = {
    "BAR-EN-101": {
        "libelle": "Isolation de combles ou de toitures",
        "termes": r"\b(?:combles?(?:\s+perdus?)?|rampants?|souffl(?:age|[ée]e?)|en\s+vrac|sarking|d[ée]roul[ée]|rouleaux?|isolation\s+du\s+toit)\b",
        "elements": ISOLATION,
        "rge": ["Isolation du toit", "Isolation des combles perdus",
                "Isolation par l'intérieur des murs ou rampants de toitures ou plafonds"],
    },
    "BAR-EN-102": {
        "libelle": "Isolation des murs",
        "termes": r"\b(?:ITE|ITI|ravalement|bardage|EMI|enduit\s+mince\s+sur\s+isolant|isolation\s+thermique\s+(?:ext|int)[ée]rieure|doublage|isolation\s+des\s+murs)\b",
        "elements": ISOLATION,
        "rge": ["Isolation par l'intérieur des murs ou rampants de toitures ou plafonds",
                "Isolation des murs par l'extérieur"],
    },
    "BAR-EN-103": {
        "libelle": "Isolation d'un plancher",
        "termes": r"\b(?:planchers?\s+bas|flocage|sous[- ]face)\b",
        "elements": ISOLATION,
        "rge": ["Isolation des murs et planchers bas", "Isolation des planchers bas"],
    },
    "BAR-EN-104": {
        "libelle": "Fenêtre ou porte-fenêtre avec vitrage isolant",
        "termes": r"\b(?:menuiseries?|fen[êe]tres?|portes?[- ]fen[êe]tres?|velux|vitrage|double\s+fen[êe]tre)\b",
        "termes_casse": r"\b(?:PF|OF)\b",
        "elements": ["Quantité (u)", "Uw", "Sw", "Surface (m²)",
                     "Marque de la menuiserie", "Référence de la menuiserie"],
        "rge": ["Fenêtres, volets, portes donnant sur l'extérieur", "Fenêtres de toit"],
    },
    "BAR-EN-105": {
        "libelle": "Isolation des toitures terrasses",
        "termes": r"\b(?:toitures?[- ]terrasses?|r[ée]fection\s+d['’]?\s?[ée]tanch[ée]it[ée]|[ée]tanch[ée]it[ée]|toitures?\s+par\s+l['’]?\s?ext[ée]rieur)\b",
        "elements": ["Surface (m²)", "Résistance thermique R", "Épaisseur (mm)",
                     "Marque de l'isolant", "Référence de l'isolant", "Certificat ACERMI", "Tableau de répartition"],
        "rge": ["Isolation des toitures terrasses ou des toitures par l'extérieur"],
    },
    "BAR-TH-106": {
        "libelle": "Chaudière individuelle haute performance",
        "termes": r"\b(?:chaudi[èe]res?|condensation|haute\s+performance\s+[ée]nerg[ée]tique)\b",
        "elements": ["Quantité (u)", "Marque / référence chaudière", "Puissance (W / kW)", "ETAS (%)",
                     "Marque / référence régulateur", "Classe du régulateur", "Surface habitable"],
        "rge": [],
    },
    "BAR-TH-110": {
        "libelle": "Radiateurs basse température",
        "termes": r"\b(?:basse\s+temp[ée]rature|chauffage\s+central)\b",
        "elements": ["Quantité (u)", "Mention « basse température »",
                     "Marque des radiateurs", "Référence des radiateurs"],
        "rge": [],
    },
    "BAR-TH-127": {
        "libelle": "VMC simple flux hygroréglable",
        "termes": r"\b(?:VMC|tourelles?|caissons?|bouches?\s+d['’]?\s?extraction|entr[ée]es?\s+d['’]?\s?air|hygro(?:r[ée]glable)?|ventilation\s+m[ée]canique)\b",
        "elements": ["Quantité (u)", "Hygroréglable type A / B",
                     "Marque / référence caissons ou tourelles", "Marque / référence bouches",
                     "Marque / référence entrées d'air", "Puissance absorbée pondérée (WThC/m³/h)",
                     "Surface habitable", "ATec / DTA"],
        "rge": ["Ventilation mécanique"],
    },
    "BAR-TH-158": {
        "libelle": "Émetteur électrique à régulation électronique",
        "termes": r"\b(?:radiateurs?\s+[ée]lectriques?|[ée]metteurs?\s+[ée]lectriques?|rayonnants?|r[ée]gulation\s+[ée]lectronique|fonctions\s+avanc[ée]es)\b",
        "elements": ["Quantité (u)", "Puissance (W / kW)", "Marque des radiateurs",
                     "Référence des radiateurs", "Mention NF 3 étoiles œil"],
        "rge": ["Radiateurs électriques, dont régulation"],
    },
}


# =====================================================================
# Compilation
# =====================================================================
def _flags(m):
    return 0 if m.get("casse") else re.IGNORECASE


@lru_cache(maxsize=1)
def motifs_administratifs():
    """[(catégorie, nom, regex compilée)]"""
    return [(cat, m["nom"], re.compile(m["regex"], _flags(m)))
            for cat, liste in ADMINISTRATIF.items() for m in liste]


@lru_cache(maxsize=1)
def motifs_elements():
    """[('Technique', nom, regex compilée)] + un motif « Domaine RGE » par fiche."""
    sortie = [("Technique", nom, re.compile(e["regex"], _flags(e))) for nom, e in ELEMENTS.items()]
    for code, f in FICHES.items():
        if f["rge"]:
            sortie.append(("RGE", f"Domaine RGE {code}", re.compile(_libelles(*f["rge"]), re.IGNORECASE)))
    return sortie


@lru_cache(maxsize=1)
def motifs_fiches():
    """[(code fiche, 'Terme', regex compilée)] + code fiche explicite."""
    sortie = [("*", "Code", re.compile(CODE_FICHE, re.IGNORECASE))]
    for code, f in FICHES.items():
        sortie.append((code, "Terme", re.compile(f["termes"], re.IGNORECASE)))
        if f.get("termes_casse"):
            sortie.append((code, "Terme", re.compile(f["termes_casse"])))
    return sortie


def element_partout(nom):
    return nom.startswith("Domaine RGE") or ELEMENTS.get(nom, {}).get("partout", False)


@lru_cache(maxsize=None)
def a_surligner(groupe, nom):
    """False si le motif est exclu du PDF surligné (drapeau « surligner »: False)."""
    for m in ADMINISTRATIF.get(groupe, []):
        if m["nom"] == nom:
            return m.get("surligner", True)
    return ELEMENTS.get(nom, {}).get("surligner", True)
