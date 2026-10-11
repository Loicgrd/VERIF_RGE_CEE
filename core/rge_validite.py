"""
Calcul de la validité RGE à une date d'engagement, à partir des lignes ADEME (historique-rge).

Règles (vérifiées sur la doc ADEME et sur l'historique réel) :
- lien_date_debut / lien_date_fin : période de qualification transmise par l'organisme.
  ⚠️ lien_date_fin n'est PAS raccourci en cas de retrait / suspension.
- date_debut / date_fin : période de présence de la ligne dans la base ADEME.
  date_debut = date de création de la ligne (pas le début de la qualification).
  Quand une qualification est retirée/suspendue, la ligne est clôturée (date_fin) et
  aucune ligne ne prend le relais → « trou » de présence.

Une date est VALIDE si :
  1. elle est couverte par une période lien_date_debut → lien_date_fin (périodes fusionnées) ;
  2. ET elle ne tombe pas dans un trou de présence ADEME postérieur à la 1re apparition ;
  3. ET (mode local) elle n'est pas postérieure à la date de la sauvegarde.
Un trou court (≤ TOLERANCE_TROU_JOURS, souvent un délai de traitement ADEME) donne
« À vérifier », jamais « Valide ».
"""
from datetime import date, datetime, timedelta

VALIDE, A_VERIFIER, EXPIRE = "valide", "a_verifier", "expire"
TOLERANCE_TROU_JOURS = 4
_UN_JOUR = timedelta(days=1)
_INFINI = date(9999, 12, 31)


def _d(val):
    """Convertit une date ADEME ('2025-10-16', '2025-10-16T00:00:00', date…) en date, ou None."""
    if val is None or val == "" or (isinstance(val, float) and val != val):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _fusionner(intervalles, ecart_max=1):
    """Fusionne des [debut, fin] dont le suivant commence au plus `ecart_max` jour(s) après la fin."""
    blocs = []
    for deb, fin in sorted(intervalles):
        if blocs and deb <= blocs[-1][1] + timedelta(days=ecart_max):
            blocs[-1][1] = max(blocs[-1][1], fin)
        else:
            blocs.append([deb, fin])
    return blocs


def _soustraire(blocs, trous):
    """Retire les trous (intervalles fermés) des blocs."""
    res = []
    for deb, fin in blocs:
        morceaux = [[deb, fin]]
        for t_deb, t_fin in trous:
            suite = []
            for m_deb, m_fin in morceaux:
                if t_fin < m_deb or t_deb > m_fin:
                    suite.append([m_deb, m_fin])
                    continue
                if m_deb < t_deb:
                    suite.append([m_deb, t_deb - _UN_JOUR])
                if t_fin < m_fin:
                    suite.append([t_fin + _UN_JOUR, m_fin])
            morceaux = suite
        res.extend(morceaux)
    return res


def _lignes_normalisees(lignes):
    out = []
    for l in lignes:
        lien_deb = _d(l.get("lien_date_debut"))
        lien_fin = _d(l.get("lien_date_fin")) or _d(l.get("date_fin"))
        pres_deb = _d(l.get("date_debut")) or lien_deb
        pres_fin = _d(l.get("date_fin"))
        if not lien_deb or not lien_fin or lien_fin < lien_deb:
            continue  # ligne inexploitable : ignorée (jamais comptée comme valide)
        out.append({
            "lien_debut": lien_deb,
            "lien_fin": lien_fin,
            "pres_debut": pres_deb,
            "pres_fin": pres_fin or _INFINI,
            "n_certif": _code_certif(l.get("_id")),
            "url": l.get("url_qualification") or l.get("lien_certificat") or "",
            "organisme": str(l.get("organisme") or "").lower().strip(),
        })
    return out


def _code_certif(id_complet):
    if not id_complet:
        return "N/A"
    s = str(id_complet).strip()
    s = s[: s.find("-")] if "-" in s else s
    return s[1:] if s.startswith("Q") else s


def analyser_domaine(lignes, date_eng, date_limite_donnees=None):
    """
    Analyse un domaine à la date d'engagement.

    date_limite_donnees : date de la sauvegarde locale (None si API ADEME en direct).
    Retourne un dict : statut, motif, debut, fin, n_certif, url, intervalles, trous.
    """
    date_eng = _d(date_eng)
    lignes = _lignes_normalisees(lignes)
    if not lignes:
        return {"statut": EXPIRE, "motif": "Aucune ligne ADEME exploitable", "debut": None, "fin": None,
                "n_certif": "N/A", "url": "", "intervalles": [], "trous": []}

    limite = date_limite_donnees or _INFINI

    # 1. Périodes de qualification (organisme)
    blocs_lien = _fusionner([(l["lien_debut"], l["lien_fin"]) for l in lignes])

    # 2. Présence dans la base ADEME et trous de présence
    blocs_pres = _fusionner([(l["pres_debut"], min(l["pres_fin"], limite)) for l in lignes])
    trous = [(a[1] + _UN_JOUR, b[0] - _UN_JOUR) for a, b in zip(blocs_pres, blocs_pres[1:])]
    if blocs_pres[-1][1] < _INFINI:
        trous.append((blocs_pres[-1][1] + _UN_JOUR, _INFINI))

    intervalles = _soustraire(blocs_lien, trous)

    # Statut
    dans_lien = any(a <= date_eng <= b for a, b in blocs_lien)
    trou = next((t for t in trous if t[0] <= date_eng <= t[1]), None)
    intervalle = next((iv for iv in intervalles if iv[0] <= date_eng <= iv[1]), None)

    if intervalle:
        statut, motif = VALIDE, ""
    elif not dans_lien:
        statut, motif = EXPIRE, "Date hors période de qualification"
    elif date_limite_donnees and date_eng > date_limite_donnees:
        statut = A_VERIFIER
        motif = f"Base locale arrêtée au {date_limite_donnees:%d/%m/%Y} : vérifier sur l'ADEME"
        if trou and trou[0] <= date_limite_donnees:
            motif = f"Retirée de l'ADEME le {trou[0]:%d/%m/%Y} ; " + motif
    elif retroactives := [l for l in lignes if l["pres_debut"] > date_eng and l["lien_debut"] <= date_eng <= l["lien_fin"]]:
        # Absente de l'ADEME à la date, mais un certificat publié plus tard couvre la date
        # (renouvellement enregistré en retard / antidaté) : jamais « Valide » d'office.
        statut = A_VERIFIER
        l = min(retroactives, key=lambda x: x["pres_debut"])
        motif = (f"Absente de l'ADEME à cette date ; certificat publié le {l['pres_debut']:%d/%m/%Y} "
                 f"couvrant rétroactivement à partir du {l['lien_debut']:%d/%m/%Y}")
    elif trou and trou[1] != _INFINI and (trou[1] - trou[0]).days + 1 <= TOLERANCE_TROU_JOURS:
        statut = A_VERIFIER
        motif = f"Absente de l'ADEME du {trou[0]:%d/%m/%Y} au {trou[1]:%d/%m/%Y} (délai de mise à jour probable)"
    else:
        statut = EXPIRE
        motif = (f"Retirée de l'ADEME le {trou[0]:%d/%m/%Y} (retrait, suspension ou changement de SIRET), "
                 f"malgré une fin théorique ultérieure") if trou else "Date hors période de qualification"

    # Période affichée : celle qui contient la date, sinon la plus proche
    if intervalle:
        debut, fin = intervalle
    elif intervalles:
        debut, fin = min(intervalles, key=lambda iv: min(abs((date_eng - iv[0]).days), abs((date_eng - iv[1]).days)))
    else:
        debut, fin = blocs_lien[-1]

    # Certificat : celui publié à la date d'engagement, sinon le plus proche
    presentes = [l for l in lignes if l["pres_debut"] <= date_eng <= l["pres_fin"] and l["lien_debut"] <= date_eng <= l["lien_fin"]]
    couvrantes = [l for l in lignes if l["lien_debut"] <= date_eng <= l["lien_fin"]]
    if presentes:
        cert = max(presentes, key=lambda l: l["pres_debut"])
    elif couvrantes:
        cert = min(couvrantes, key=lambda l: abs((l["pres_debut"] - date_eng).days))
    else:
        cert = max(lignes, key=lambda l: (l["lien_fin"], l["pres_debut"]))

    return {"statut": statut, "motif": motif, "debut": debut, "fin": fin,
            "n_certif": cert["n_certif"], "url": cert["url"],
            "intervalles": intervalles, "trous": trous}


def analyser_lignes(api_lines, date_eng, date_limite_donnees=None):
    """Regroupe les lignes ADEME par domaine et analyse chacun. Retourne {domaine: résultat}."""
    par_domaine = {}
    for l in api_lines:
        par_domaine.setdefault(str(l.get("domaine") or "Inconnu").strip(), []).append(l)
    return {dom: analyser_domaine(lignes, date_eng, date_limite_donnees) for dom, lignes in par_domaine.items()}
