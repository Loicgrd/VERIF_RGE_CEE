"""
Motifs CEE à repérer automatiquement dans les PDF OCRisés (page 5_Recherche_OCR).
Sources : méthode d'instruction + « Règles par type de document » + « Règles techniques ».

Chaque motif :
    nom       : libellé affiché
    regex     : expression régulière (c'est le match complet qui est affiché)
    casse     : True = sensible à la casse (par défaut : insensible)
    presence  : True = apparaît dans la synthèse « présent / absent »
    note      : aide (optionnel)

Les regex tolèrent les espaces et tirets parasites de l'OCR.
Pour ajouter un motif : ajouter un dict dans la bonne catégorie, rien d'autre à modifier.
"""
import re
from functools import lru_cache

MOIS = r"(?:janv|f[ée]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[ée]c)\w*\.?"
APOS = r"['’]?\s?"
OEUVRE = r"(?:oe|œ)uvre"
NUM = r"\s*(?:n[°o]|num[ée]ro|r[ée]f[ée]rence|r[ée]f\.?)\s*:?\s*"  # « n° », « numéro », « réf. »…


def _libelles(*textes):
    """Libellés exacts → regex tolérante (espaces multiples, apostrophes, accents perdus à l'OCR)."""
    alts = []
    for t in textes:
        rx = re.escape(t).replace(r"\ ", " ").replace(" ", r"\s+")
        rx = rx.replace("'", "['’]").replace("é", "[ée]").replace("è", "[èe]")
        alts.append(rx)
    return r"\b(?:" + "|".join(alts) + r")\b"


MOTIFS = {
    # ------------------------------------------------------------------
    "Identification": [
        {"nom": "Code fiche", "presence": True,
         "regex": r"\bBA[RT]\s?[-–]?\s?(?:EN|TH|EQ|SE)\s?[-–]?\s?\d{3}\b"},
        {"nom": "SIRET", "presence": True,
         "regex": r"\b\d{3}\s?\d{3}\s?\d{3}\s?\d{5}\b",
         "note": "Validation RGE obligatoirement au SIRET (le SIREN seul ne suffit pas)"},
        {"nom": "SIREN (après le mot SIREN)",
         "regex": r"\bSIREN\s*:?\s*\d{3}\s?\d{3}\s?\d{3}\b"},
        {"nom": "TVA intracommunautaire",
         "regex": r"\bFR\s?[0-9A-Z]{2}\s?\d{3}\s?\d{3}\s?\d{3}\b"},
        {"nom": "N° dossier ODICEE",
         "regex": r"\bODICEE\b[^\n]{0,25}?\d[\w/-]{3,}",
         "note": "Première page de l'AH et en-tête de la demande de VISA"},
        {"nom": "Demande de VISA", "regex": r"\bdemande\s+de\s+visa\b"},
    ],
    # ------------------------------------------------------------------
    "Lien fort (adresse / marché / lot)": [
        {"nom": "Adresse (n° + voie)", "presence": True,
         "regex": r"\b\d{1,4}\s?(?:bis|ter)?,?\s+(?:rue|av(?:enue)?\.?|bd|boulevard|chemin|all[ée]e|impasse"
                  r"|place|route|quai|cours|r[ée]sidence|square|lotissement)\b(?:\s+[^\d\s]+){1,4}",
         "note": "N° + type de voie + jusqu'à 4 mots (s'arrête au premier nombre, ex. le CP)"},
        {"nom": "Code postal + ville", "casse": True,
         "regex": r"(?<![\w-])(?:0[1-9]|[1-8]\d|9[0-5]|2[AB])\d{3}\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’]+(?:-[A-Za-zÀ-ÿ'’]+)*"},
        {"nom": "Résidence / lieu des travaux",
         "regex": r"\b(?:r[ée]sidence|cit[ée]|groupe|ensemble\s+immobilier|b[âa]timent|b[âa]t\.)\s+[^\d\s]+(?:\s+[^\d\s]+){0,3}"},
        {"nom": "N° de marché", "presence": True,
         "regex": rf"\bmarch[ée]{NUM}[\w/.-]*\d[\w/.-]*",
         "note": "Si préfixe alphabétique, seuls les chiffres sont à comparer"},
        {"nom": "N° de commande",
         "regex": rf"\b(?:commande|BC){NUM}[\w/.-]*\d[\w/.-]*"},
        {"nom": "N° de lot", "presence": True,
         "regex": r"\blot\s*(?:n[°o])?\s*:?\s*\d{1,3}\b"},
        {"nom": "Objet du marché / opération",
         "regex": r"\b(?:objet\s+du\s+march[ée]|objet\s+des\s+travaux|nom\s+de\s+l['’]?\s?op[ée]ration|op[ée]ration\s*:)"},
    ],
    # ------------------------------------------------------------------
    "Pièces engagement / réalisation": [
        {"nom": "Devis", "presence": True, "regex": r"\bdevis\b"},
        {"nom": "N° de devis", "regex": rf"\bdevis{NUM}[\w/.-]*\d[\w/.-]*"},
        {"nom": "Validité du devis", "regex": r"\b(?:valable|validit[ée]\s+(?:du\s+devis|de\s+l['’]?\s?offre)|dur[ée]e\s+de\s+validit[ée])\b"},
        {"nom": "Acte d'engagement", "presence": True,
         "regex": rf"\bacte\s+d{APOS}engagement\b"},
        {"nom": "Ordre de service", "presence": True, "regex": r"\bordre\s+de\s+service\b"},
        {"nom": "N° d'OS", "regex": r"\b(?:OS|ordre\s+de\s+service)\s*(?:n[°o])?\s*:?\s*\d{1,3}\b",
         "note": "Seul l'OS n°1 vaut engagement"},
        {"nom": "Bon / lettre de commande ou de travaux", "presence": True,
         "regex": r"\b(?:bon|lettre)\s+de\s+(?:commande|travaux)\b"},
        {"nom": "Démarrage / préparation des travaux",
         "regex": r"\b(?:d[ée]marrage|commencement|d[ée]but|pr[ée]paration)\s+des\s+travaux\b"},
        {"nom": "Facture", "presence": True, "regex": r"\bfacture\b"},
        {"nom": "N° de facture", "regex": rf"\bfacture{NUM}[\w/.-]*\d[\w/.-]*"},
        {"nom": "Situation / avancement",
         "regex": r"\b(?:situation(?:\s+de\s+travaux)?(?:\s*n[°o]?\s?\d+)?|avancement)\b"},
        {"nom": "DGD", "presence": True,
         "regex": r"\b(?:DGD|d[ée]compte\s+g[ée]n[ée]ral(?:\s+(?:et\s+)?d[ée]finitif)?)\b"},
        {"nom": "DPGF", "presence": True,
         "regex": r"\b(?:DPGF|d[ée]composition\s+du\s+prix\s+global\s+et\s+forfaitaire)\b"},
        {"nom": "PV de réception", "presence": True,
         "regex": r"\b(?:PV|proc[èe]s[- ]?verbal)\s+de\s+r[ée]ception\b"},
        {"nom": "Réception avec / sans réserves", "presence": True,
         "regex": r"\b(?:sans|avec)\s+r[ée]serves?\b"},
        {"nom": "PV de levée des réserves",
         "regex": r"\b(?:(?:PV|proc[èe]s[- ]?verbal)\s+de\s+)?lev[ée]e\s+des\s+r[ée]serves\b"},
        {"nom": "Avenant", "regex": r"\bavenant\b"},
        {"nom": "Abréviations (AE, OS, BC, BT)", "casse": True,
         "regex": r"\b(?:AE|OS|BC|BT)\b"},
    ],
    # ------------------------------------------------------------------
    "Dates et montants": [
        {"nom": "Date (numérique)",
         "regex": r"\b\d{1,2}\s?([/.-])\s?\d{1,2}\s?\1\s?(?:\d{4}|\d{2})\b",
         "note": "Même séparateur imposé (12/03/2025, 12.03.25…)"},
        {"nom": "Date (en lettres)", "regex": rf"\b\d{{1,2}}(?:er)?\s+{MOIS}\s+\d{{4}}\b"},
        {"nom": "Mois + année seuls", "regex": rf"\b(?<!\d\s){MOIS}\s+\d{{4}}\b",
         "note": "Date sans jour : on retient le dernier jour du mois"},
        {"nom": "Date de visite préalable", "regex": r"\bvisite\s+pr[ée]alable\b"},
        {"nom": "Montant (€)",
         "regex": r"\b\d{1,3}(?:[ . ]?\d{3})*,\d{2}\s?(?:€|EUR)"},
        {"nom": "Total HT", "presence": True,
         "regex": r"\b(?:total|montant)\s+(?:g[ée]n[ée]ral\s+)?(?:HT|hors\s+taxes?)\b[^\n]{0,20}?\d[\d . ]*,\d{2}",
         "note": "Lien fort : tolérance 0,01 €"},
        {"nom": "Mention HT / TTC", "regex": r"\b(?:HT|TTC|hors\s+taxes?|toutes\s+taxes)\b"},
        {"nom": "Avancement 100 %", "regex": r"\b100\s?%"},
    ],
    # ------------------------------------------------------------------
    "Signatures / parties": [
        {"nom": "Maîtrise d'ouvrage (MOA)", "presence": True,
         "regex": rf"\b(?:ma[îi]tr(?:e|ise)\s+d{APOS}ouvrage|MOA)\b"},
        {"nom": "Maîtrise d'œuvre (MOE)",
         "regex": rf"\b(?:ma[îi]tr(?:e|ise)\s+d{APOS}{OEUVRE}|MOE)\b"},
        {"nom": "Titulaire / co-traitant", "regex": r"\b(?:titulaire|co[- ]?traitant|mandataire)\b"},
        {"nom": "Signature / bon pour accord", "presence": True,
         "regex": r"\b(?:signature|sign[ée]|bon\s+pour\s+accord|lu\s+et\s+approuv[ée])\b"},
        {"nom": "Signature électronique",
         "regex": r"\b(?:signature\s+[ée]lectronique|sign[ée]\s+[ée]lectroniquement|docusign|yousign|universign)\b",
         "note": "Si valide : nom, prénom et fonction du signataire non nécessaires"},
        {"nom": "Cachet / tampon", "regex": r"\b(?:cachet|tampon)\b"},
        {"nom": "Fonction du signataire",
         "regex": r"\b(?:qualit[ée]|fonction)\s+du\s+signataire\b|\b(?:nom|pr[ée]nom)\s+du\s+signataire\b"},
    ],
    # ------------------------------------------------------------------
    "RGE / sous-traitance": [
        {"nom": "Organisme RGE", "presence": True,
         "regex": r"\b(?:RGE|Qualibat|Qualifelec|QualiPAC|Quali['’]?EnR|Qualibois|QualiSol|Eurovent|Certibat)\b"},
        {"nom": "Domaine RGE (libellé exact)", "presence": True,
         "regex": _libelles(
             "Isolation du toit", "Isolation des combles perdus",
             "Isolation par l'intérieur des murs ou rampants de toitures ou plafonds",
             "Isolation des murs par l'extérieur", "Isolation des murs et planchers bas",
             "Isolation des planchers bas", "Fenêtres, volets, portes donnant sur l'extérieur",
             "Fenêtres de toit", "Isolation des toitures terrasses ou des toitures par l'extérieur",
             "Ventilation mécanique", "Radiateurs électriques, dont régulation"),
         "note": "Libellés du tableau des domaines RGE par fiche BAR"},
        {"nom": "N° de qualification / certification",
         "regex": r"\b(?:qualification|certificat(?:ion)?|num[ée]ro\s+client|n[°o]\s+client)\s*(?:n[°o])?\s*:?\s*[A-Z]{0,3}-?[A-Z]?\s?\d{4,8}\b",
         "note": "Qualifelec : le « numéro client » sert de n° de certification"},
        {"nom": "N° Qualibat (à valider)", "casse": True,
         "regex": r"\bE-?E?\s?\d{5,7}\b",
         "note": "Format à valider sur des certificats réels"},
        {"nom": "Date d'attribution / validité",
         "regex": r"\b(?:date\s+d['’]?\s?attribution|attribu[ée]e?\s+le|valable\s+(?:du|jusqu)|valide\s+jusqu|p[ée]riode\s+de\s+validit[ée]|date\s+d['’]?\s?(?:expiration|[ée]ch[ée]ance))\b"},
        {"nom": "Sous-traitance", "presence": True,
         "regex": r"\b(?:sous[- ]?trait\w*|DC\s?4)\b"},
        {"nom": "Déclaration de sous-traitance (DC4)",
         "regex": r"\b(?:d[ée]claration\s+de\s+sous[- ]?traitance|DC\s?4)\b"},
    ],
    # ------------------------------------------------------------------
    "Attestation sur l'honneur": [
        {"nom": "Attestation sur l'honneur", "presence": True,
         "regex": rf"\battestation\s+sur\s+l{APOS}honneur\b"},
        {"nom": "Partie A (A, A1…An)", "casse": True,
         "regex": r"(?:^|\s)A\d{0,2}\s?[/.)]\s"},
        {"nom": "Partie B – Bénéficiaire",
         "regex": r"\bB\s?[/.)]?\s*b[ée]n[ée]ficiaire\s+de\s+l['’]?\s?op[ée]ration\b"},
        {"nom": "Partie C – Professionnel / MOE",
         "regex": rf"\bC\s?[/.)]?\s*professionnel\s+ayant\s+mis\s+en\s+{OEUVRE}\b"},
        {"nom": "Partie BS – Bailleur social",
         "regex": r"\bBS\s?[/.)]?\s*bailleur\s+social\b"},
        {"nom": "Nombre total de ménages",
         "regex": r"\bnombre\s+total\s+de\s+m[ée]nages\b[^\n]{0,15}?\d*"},
        {"nom": "Ménages en logement conventionné",
         "regex": r"\blogements?\s+conventionn[ée]s?\b"},
        {"nom": "Pagination (page x/y)",
         "regex": r"\b(?:page|p\.)\s*\d{1,3}\s*(?:/|sur)\s*\d{1,3}\b"},
    ],
    # ------------------------------------------------------------------
    "Valeurs techniques": [
        {"nom": "Résistance thermique R",
         "regex": r"\bR\s?[=:]\s?\d{1,2}[.,]\d{1,2}(?:\s?m[²2]\s?[.·]?\s?K\s?/\s?W)?"
                  r"|\b\d{1,2}[.,]\d{1,2}\s?m[²2]\s?[.·/]?\s?K\s?/\s?W"},
        {"nom": "Épaisseur (mm)", "regex": r"\b(?:[ée]p(?:aisseur)?\.?\s*:?\s*)?\d{2,3}\s?mm\b"},
        {"nom": "Surface (m²)", "regex": r"\b\d+(?:[ .]\d{3})*(?:[.,]\d+)?\s?m[²2](?![\s.·/]*K)"},
        {"nom": "Surface habitable", "regex": r"\bsurface\s+habitable\b"},
        {"nom": "Uw / Sw", "regex": r"\b(?:Uw|Sw)\s?[=:]?\s?\d[.,]\d{1,2}"},
        {"nom": "ETAS / efficacité saisonnière",
         "regex": r"\b(?:[ée]tas|efficacit[ée]\s+[ée]nerg[ée]tique\s+saisonni[èe]re)\b[^\n]{0,30}?\d{2,3}\s?%"},
        {"nom": "Puissance (W / kW)", "regex": r"(?<![/.])\b\d+(?:[.,]\d+)?\s?k?W\b(?!\s?h)"},
        {"nom": "Puissance absorbée pondérée (WThC/m³/h)",
         "regex": r"\b\d+(?:[.,]\d+)?\s?W\s?-?\s?Th\s?-?\s?C\s?/\s?m[3³]\s?/\s?h\b"},
        {"nom": "Classe du régulateur",
         "regex": r"\bclasse\s+(?:VIII|VII|VI|IV|V|III|II|I|[1-8])\b"},
        {"nom": "Quantité (u)", "regex": r"\b\d+\s?(?:u|U|unit[ée]s?|ens\.?)\b"},
        {"nom": "COP / SCOP", "regex": r"\bS?COP\s?[=:]?\s?\d[.,]\d{1,2}"},
        {"nom": "Certificat ACERMI",
         "regex": r"\bACERMI\b(?:[^\n]{0,15}?\d{2}\s?/\s?\d{3}\s?/\s?\d{3,4})?",
         "note": "À lire si marque et référence de l'isolant sont sur la preuve de réalisation"},
        {"nom": "ATec / DTA",
         "regex": r"\b(?:ATec|Avis\s+Technique|DTA)\b[^\n]{0,20}?\d{1,2}(?:\.\d)?\s?/\s?\d{2}\s?-\s?\d{3,4}(?:_V\d)?"},
        {"nom": "Tableau de répartition", "regex": r"\b(?:tableau|r[ée]partition)\s+(?:de\s+)?(?:r[ée]partition\s+)?des\s+surfaces\b|\btableau\s+de\s+r[ée]partition\b"},
    ],
    # ------------------------------------------------------------------
    "Termes techniques par fiche": [
        {"nom": "EN-101 Combles / rampants",
         "regex": r"\b(?:combles?\s+perdus?|rampants?|souffl(?:age|[ée]e?)|en\s+vrac|sarking|d[ée]roul[ée]|rouleaux?)\b"},
        {"nom": "EN-102 Murs (ITE / ITI)",
         "regex": r"\b(?:ITE|ITI|ravalement|bardage|EMI|enduit\s+mince\s+sur\s+isolant|isolation\s+thermique\s+(?:ext|int)[ée]rieure|doublage)\b"},
        {"nom": "EN-103 Planchers bas",
         "regex": r"\b(?:planchers?\s+bas|flocage|sous[- ]face)\b"},
        {"nom": "EN-104 Menuiseries",
         "regex": r"\b(?:menuiseries?|fen[êe]tres?(?:\s+de\s+toit(?:ure)?)?|portes?[- ]fen[êe]tres?|double\s+fen[êe]tre|velux|vitrage)\b"},
        {"nom": "EN-104 Abréviations (PF, OF)", "casse": True, "regex": r"\b(?:PF|OF)\b"},
        {"nom": "EN-105 Toiture terrasse",
         "regex": r"\b(?:toitures?[- ]terrasses?|r[ée]fection\s+d['’]?\s?[ée]tanch[ée]it[ée]|[ée]tanch[ée]it[ée])\b"},
        {"nom": "TH-106 Chaudière",
         "regex": r"\b(?:chaudi[èe]re|condensation|r[ée]gulateur|r[ée]gulation)\b"},
        {"nom": "TH-110 Radiateur basse température",
         "regex": r"\bbasse\s+temp[ée]rature\b"},
        {"nom": "TH-127 VMC",
         "regex": r"\b(?:VMC|tourelles?|caissons?|bouches?\s+d['’]?\s?extraction|entr[ée]es?\s+d['’]?\s?air|hygro(?:r[ée]glable)?\s*(?:type\s*)?[AB]?)\b"},
        {"nom": "TH-158 Radiateur électrique",
         "regex": r"\b(?:radiateurs?|[ée]metteurs?|rayonnants?|r[ée]gulation\s+[ée]lectronique)\b"},
        {"nom": "TH-158 Mention NF 3 étoiles œil",
         "regex": r"\bNF\b[^\n]{0,40}?(?:3\s?\*|3\s?[ée]toiles?|(?:oe|œ)il)"},
    ],
}


@lru_cache(maxsize=1)
def motifs_compiles():
    """Retourne [(catégorie, motif, regex compilée), ...]."""
    sortie = []
    for cat, liste in MOTIFS.items():
        for m in liste:
            flags = 0 if m.get("casse") else re.IGNORECASE
            sortie.append((cat, m, re.compile(m["regex"], flags)))
    return sortie
