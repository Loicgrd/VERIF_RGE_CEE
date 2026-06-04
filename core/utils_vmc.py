import datetime
import re
from collections import defaultdict

# --- LE PROMPT (Cerveau de l'IA pour le pré-remplissage) ---
PROMPT_VMC = """
Tu es un Ingénieur Expert en conformité documentaire pour les Certificats d'Économies d'Énergie (CEE).
Analyse cet Avis Technique (ATec) du CSTB.

Extrais les informations au format JSON strict avec la structure exacte suivante :
{
  "est_vmc": true,
  "numero_atec": "Ex: 14.5/17-2273",
  "indice_revision": "Ex: 'V2', 'Modificatif 1' ou 'V1' si non précisé",
  "titulaire": "Le(s) constructeur(s) officiel(s)",
  "distributeur": "La marque commerciale. Si aucune marque distincte, remets le titulaire.",
  "debut_validite": "YYYY-MM-DD",
  "fin_validite": "YYYY-MM-DD",
  "modeles": [
    {
      "nom_modele": "Le nom de base de la gamme (ex: EASYVEC)",
      "type_logement": "'Individuel', 'Collectif' ou 'Mixte'",
      "basse_pression": true ou false,
      "double_flux": true ou false,
      "debits_disponibles": ["400", "700"],
      "puissance_hygro_a": "Ex: '14.0'",
      "puissance_hygro_b": "Ex: '15.2'"
    }
  ]
}

RÈGLES D'EXTRACTION ABSOLUES :
1. FILTRE HORS PÉRIMÈTRE : Si le document ne traite pas de VMC, mets "est_vmc": false.
2. TITULAIRE ET DISTRIBUTEUR : "titulaire" (Constructeur), "distributeur" (Marque commerciale).
3. IDENTIFICATION DES CAISSONS ET DÉBITS (RÈGLE STRICTE) :
   - Isole le nom de base de la gamme.
   - DÉBITS : Les débits sont UNIQUEMENT les chiffres qui suivent immédiatement le nom du modèle dans le texte (ex: "400" et "700" pour EASYVEC 400 et EASYVEC 700). IL EST STRICTEMENT INTERDIT de lire ou d'extraire des débits à l'intérieur des tableaux.
   - REGROUPEMENT : Si plusieurs déclinaisons de débits, crée UN SEUL objet et liste-les dans `debits_disponibles`.
   - ACCESSOIRES : Rejette systématiquement les chapeaux de toiture (ex: Grauli, Defa), bouches, etc.
4. TYPE DE LOGEMENT : "maisons individuelles" = "Individuel", "logements collectifs" = "Collectif", les deux = "Mixte".
5. BASSE PRESSION : true à TOUS les modèles si le système global est "Basse Pression" ou "BP". (Ne pas confondre avec Basse consommation).
6. DOUBLE FLUX : true si le document mentionne un système "Double Flux", "DF", ou un échangeur thermique.
7. PUISSANCES PONDÉRÉES (W-Th-C) - LOGIQUE SÉQUENTIELLE OBLIGATOIRE :
   - CONSIDÈRE LE DOCUMENT COMME AYANT DEUX CHAPITRES DE TABLEAUX.
   - ÉTAPE 1 (TRAITEMENT DU PREMIER TABLEAU) : 
     - Parcoure le document du haut vers le bas. Trouve la première occurrence d'un tableau contenant des données "F4" (configuration "0 1 1 0").
     - Ce premier tableau est obligatoirement le tableau "Hygro A".
     - Extraits les valeurs pour chaque modèle et stocke-les dans `puissance_hygro_a`.
   - ÉTAPE 2 (TRAITEMENT DU DEUXIÈME TABLEAU) : 
     - Continue de lire le document après le premier tableau.
     - Trouve la DEUXIÈME occurrence d'un tableau contenant des données "F4" (configuration "0 1 1 0").
     - Ce deuxième tableau est obligatoirement le tableau "Hygro B".
     - Extraits les valeurs pour chaque modèle et stocke-les dans `puissance_hygro_b`.
   - RÈGLE D'OR : Si tu extrais la même valeur pour A et pour B, c'est que tu as échoué à trouver le deuxième tableau. Cherche plus loin dans le document.
   - Ne mets que les chiffres (ex: "14.0"). Si introuvable, mets null.
8. FORMAT : Renvoie UNIQUEMENT un JSON valide.
"""

def format_debits_to_str(debits_list):
    if not isinstance(debits_list, list): return ""
    return ", ".join(str(d) for d in debits_list)

def parse_debits_from_str(debits_str):
    if not debits_str: return []
    return [d.strip() for d in str(debits_str).split(",") if d.strip()]

def filter_and_group_atec(donnees_atec, filtre_marque, filtre_texte, filtre_date):
    """Filtre les données et organise l'historique de chaque Avis"""
    resultats_filtres = []
    texte_lower = (filtre_texte or "").lower()

    for doc in donnees_atec:
        if filtre_marque != "Toutes" and doc.get('distributeur') != filtre_marque: continue

        match_texte = False
        if not texte_lower: match_texte = True
        else:
            atec_val = str(doc.get('numero_atec') or '').lower()
            dist_val = str(doc.get('distributeur') or '').lower()
            if texte_lower in atec_val or texte_lower in dist_val: match_texte = True
            else:
                modeles = doc.get('modeles') or []
                for mod in modeles:
                    if texte_lower in str(mod.get('nom_modele') or '').lower():
                        match_texte = True
                        break
        
        if not match_texte: continue

        try: deb = datetime.datetime.strptime(doc['debut_validite'], "%Y-%m-%d").date() if doc.get('debut_validite') else None
        except: deb = None
        try: fin = datetime.datetime.strptime(doc['fin_validite'], "%Y-%m-%d").date() if doc.get('fin_validite') else None
        except: fin = None

        if filtre_date:
            if deb and fin and not (deb <= filtre_date <= fin): continue
            elif deb and filtre_date < deb: continue
            elif fin and filtre_date > fin: continue

        doc_copie = dict(doc)
        doc_copie['_deb_parsed'] = deb
        resultats_filtres.append(doc_copie)

    # --- NOUVEAU : GESTION DE L'HISTORIQUE ---
    groupes = defaultdict(list)
    
    # 1. On regroupe tous les documents par "Numéro de base" (ex: 14.5/17-2273)
    for doc in resultats_filtres:
        base_num = str(doc.get('numero_atec', '')).split('_')[0].split(' ')[0]
        groupes[base_num].append(doc)

    resultats_finaux = []
    
    # 2. On trie les groupes pour afficher les familles d'Avis les plus récentes en premier
    groupes_tries = sorted(
        groupes.values(), 
        key=lambda g: max([d.get('_deb_parsed') or datetime.date.min for d in g]), 
        reverse=True
    )

    # 3. Au sein de chaque famille d'Avis, on trie du plus récent au plus ancien
    for groupe in groupes_tries:
        groupe.sort(key=lambda x: x.get('_deb_parsed') or datetime.date.min, reverse=True)
        
        # On marque le tout premier comme étant "La version actuelle"
        if len(groupe) > 0:
            groupe[0]['_est_version_recente'] = True
            for doc_ancien in groupe[1:]:
                doc_ancien['_est_version_recente'] = False
                
        resultats_finaux.extend(groupe)

    return resultats_finaux