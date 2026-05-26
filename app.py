import streamlit as st
import pandas as pd
from datetime import datetime
import requests
import io
import zipfile
import urllib.parse
import plotly.express as px

from database import fetch_local_backup


# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Vérification des RGE", layout="wide")


# On crée deux colonnes : 
# La première prend 90% de l'espace (le titre), la seconde 10% (le bouton)
c1, c2 = st.columns([0.9, 0.1])

with c1:
    st.title("🔍 Vérification des RGE")

with c2:
    # Le bouton est maintenant en haut à droite
    force_local = st.toggle(
        "🗄️ Local", 
        value=False,
        help="Forcer la base de données locale en cas de bug ou ralentissement de l'ADEME (MaJ : 19/05/2026)"
    )


# --- STYLE CSS AVANCÉ (COMPACITÉ TOTALE) ---
st.markdown("""
    <style>
    [data-testid="column"] {
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        min-width: 0px;
    }
    .certif-info {
        font-size: 12px !important;
        line-height: 1.1 !important;
    }
    div.stDownloadButton > button, div.stButton > button {
        height: 26px !important;
        width: 100% !important;
        font-size: 11px !important;
        padding: 0px !important;
        min-height: 26px !important;
    }
    .add-btn button {
        background-color: #f0f2f6 !important;
        border: 1px dashed #999 !important;
        color: #333 !important;
    }
    .stElementContainer { margin-bottom: 1px !important; }
    .stVerticalBlock { gap: 0rem !important; }
    .streamlit-expanderContent { padding: 0.5rem !important; }
    </style>
""", unsafe_allow_html=True)

# --- CONFIGURATION DES FICHES CEE ---
MAP_CEE = {
    "Fenêtres, volets, portes extérieures 2020": ["EN104", "EN108", "EN110"],
    "Isolation du toit 2020": ["EN101", "EN105", "EN106"],
    "Isolation des murs et planchers bas 2020": ["EN102", "EN103", "EN107"],
    "Isolation par l'intérieur des murs ou rampants de toitures ou plafonds": ["EN101", "EN102"],
    "Chaudière condensation ou micro-cogénération gaz ou fioul 2020": ["TH106", "TH107"],
    "Equipements électriques hors ENR : chauffage, eau chaude, éclairage 2020": ["EQ110", "EQ115"],
    "Pompe à chaleur : chauffage": ["TH171", "TH172", "TH129", "TH159"],
    "Isolation des combles perdus": ["EN101"],
    "Chauffe-Eau Thermodynamique": ["TH148", "TH169"],
    "Fenêtres, volets, portes donnant sur l'extérieur": ["EN104", "EN108"],
    "Chaudière condensation ou micro-cogénération gaz ou fioul": ["TH106", "TH107"],
    "Poêle ou insert bois": ["TH112"],
    "Isolation des murs par l'extérieur": ["EN102"],
    "Isolation des planchers bas": ["EN103"],
    "Isolation des toitures terrasses ou des toitures par l'extérieur": ["EN105"],
    "Fenêtres de toit": ["EN104"],
    "Radiateurs électriques, dont régulation.": ["TH158", "TH173"],
    "Chaudière bois": ["TH113"],
    "Panneaux solaires photovoltaïques": ["PV"],
    "Ventilation mécanique": ["TH127", "TH125", "TH155"],
    "Ventilation 2020": ["TH127", "TH125", "TH155"],
    "Audit énergétique Maison individuelle": ["TH164", "TH174"],
    "Architecte": ["TH164", "TH174"],
    "Chauffage et/ou eau chaude solaire": ["TH101", "TH143", "TH124"],
    "Pompe à chaleur et/ou Chauffe-eau thermodynamique 2020": ["TH171", "TH148", "TH159"],
    "Chauffage et/ou eau chaude au bois 2020": ["TH113", "TH112"],
    "Audit énergétique Logement collectif": ["TH145"],
    "Projet complet de rénovation": ["TH164", "TH145", "TH174"],
    "Chauffage et/ou eau chaude solaire 2020": ["TH101", "TH143"],
    "Forage géothermique": ["TH178"],
}

def consolider_periodes(results):
    if not results:
        return None
    
    # Conversion propre des dates pour comparaison
    for r in results:
        r['dateDebut'] = pd.to_datetime(r['dateDebutValidite'])
        r['dateFin'] = pd.to_datetime(r['dateFinValidite'])
    
    # Tri temporel
    results = sorted(results, key=lambda x: x['dateDebut'])
    
    # Algorithme de fusion
    globale = results[0]
    for p in results[1:]:
        # Si la période suivante commence dans les 31 jours après la fin de la précédente
        if p['dateDebut'] <= globale['dateFin'] + pd.Timedelta(days=31):
            globale['dateFin'] = max(globale['dateFin'], p['dateFin'])
        else:
            # On s'arrête ici si il y a une vraie cassure dans la validité
            break 
            
    return globale

def extract_qualif_code(id_complet):
    if not id_complet or id_complet == "N/A": return "N/A"
    id_str = str(id_complet).strip()
    pos_tiret = id_str.find("-")
    longueur_fin = len(id_str) if pos_tiret == -1 else pos_tiret
    return id_str[1:longueur_fin] if id_str.startswith("Q") else id_str[:longueur_fin]

def clean_url(url):
    return urllib.parse.quote(url, safe=':/?&=') if url else ""

def get_cee_options(domaine):
    dom_clean = str(domaine).lower().strip()
    for key, codes in MAP_CEE.items():
        if key.lower() in dom_clean: return codes
    return ["RGE"]

def fetch_ademe_data(siret, force_local=False):
    url = f"https://data.ademe.fr/data-fair/api/v1/datasets/historique-rge/lines?q=siret.exact:'{siret}'&size=1000"
    
    # Si le bouton glissant est activé
    if force_local:
        st.info(f"🗄️ Mode local forcé pour le SIRET {siret}")
        return fetch_local_backup(siret)  # Appel de la fonction importée
        
    # Mode normal avec bascule automatique si l'API crash
    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            return r.json().get('results', [])
        else:
            raise requests.exceptions.RequestException()
    except (requests.exceptions.RequestException, Exception):
        st.warning(f"⚠️ Mode secours : Base ADEME injoignable. Recherche locale pour le SIRET {siret}")
        return fetch_local_backup(siret)  # Appel de la fonction importée



c_date, _ = st.columns([1, 2])
with c_date:
    date_eng = st.date_input("Date d'engagement :", datetime.now(), format="DD/MM/YYYY")

if 'siret_rows' not in st.session_state:
    st.session_state.siret_rows = pd.DataFrame([{"SIRET": ""}], dtype=str)

df_saisie = st.data_editor(st.session_state.siret_rows, num_rows="dynamic", use_container_width=True,
                           column_config={"SIRET": st.column_config.TextColumn("SIRET", max_chars=14)})

if st.button("🔍 Analyser les SIRET", type="primary"):
    sirets = [str(s).strip() for s in df_saisie["SIRET"] if s and str(s).strip()]
    if not sirets:
        st.warning("Veuillez saisir au moins un SIRET.")
    else:
        if 'audit_results' in st.session_state:
            del st.session_state.audit_results
        all_results = []
        with st.spinner("Analyse ADEME..."):
            for s in sirets:
                api_lines = fetch_ademe_data(s, force_local=force_local)
                if api_lines:
                    nom_ent = api_lines[0].get('nom_entreprise') or api_lines[0].get('raison_sociale') or "Inconnu"
                    domaines_raw = {}
                    for line in api_lines:
                        dom = str(line.get('domaine', 'Inconnu')).strip()
                        
                        # --- EXTRACTS DES DATES CLÉS ---
                        lien_debut = line.get('lien_date_debut')
                        lien_fin = line.get('lien_date_fin') or line.get('date_fin')
                        tech_debut = line.get('date_debut') or line.get('lien_date_debut')
                        
                        if lien_debut and lien_fin:
                            try:
                                # Conversion en objets date de Python
                                d_lien_debut = datetime.strptime(lien_debut[:10], '%Y-%m-%d').date()
                                d_lien_fin = datetime.strptime(lien_fin[:10], '%Y-%m-%d').date()
                                d_tech_debut = datetime.strptime(tech_debut[:10], '%Y-%m-%d').date()
                                
                                if dom not in domaines_raw: 
                                    domaines_raw[dom] = []
                                    
                                domaines_raw[dom].append({
                                    "n_certif": extract_qualif_code(line.get('_id', "N/A")), 
                                    "debut": d_lien_debut,         # Pour l'affichage de la timeline
                                    "fin": d_lien_fin,             # Date de fin officielle (Excel/Écran)
                                    "lien_debut_regle": d_lien_debut,
                                    "tech_debut_score": d_tech_debut, # Date d'extraction pour le calcul de distance
                                    "url": clean_url(line.get('url_qualification') or line.get('lien_certificat'))
                                })
                            except: 
                                continue
                    # --- MOTEUR DE SÉLECTION ROBUSTE (SPÉCIAL ANOMALIES ADEME) ---
                    domaines_finaux = {}
                    for dom, periodes in domaines_raw.items():
                        # Étape 1 : On garde les lignes dont la période globale couvre la date d'engagement
                        lignes_valides = [
                            p for p in periodes 
                            if p['lien_debut_regle'] <= date_eng <= p['fin']
                        ]
                        
                        if lignes_valides:
                            # Étape 2 : On prend la ligne extraite au plus près de notre date d'engagement 
                            # (Résout le cas du PDF de 2024 encapsulé dans un log de 2025)
                            meilleure_ligne = min(
                                lignes_valides, 
                                key=lambda x: abs((x['tech_debut_score'] - date_eng).days)
                            )
                            domaines_finaux[dom] = {**meilleure_ligne, "status_rge": True, "historique": periodes}
                        else:
                            # Fallback : Si aucun certificat ne couvrait cette date, l'entreprise est KO.
                            # On récupère le certificat le plus récent de l'historique pour consultation.
                            plus_recente = max(periodes, key=lambda x: x['fin'])
                            domaines_finaux[dom] = {**plus_recente, "status_rge": False, "historique": periodes}
                    all_results.append({"SIRET": s, "Entreprise": nom_ent, "Domaines": domaines_finaux})

        if not all_results:
            st.error("❌ Aucun résultat trouvé pour le(s) SIRET saisis.")
        else:
            st.session_state.audit_results = all_results
            #st.success(f"✅ Analyse terminée : {len(all_results)} entreprise(s) trouvée(s).")

if 'audit_results' in st.session_state:
    files_to_zip, excel_data = [], []

    for res in st.session_state.audit_results:
        with st.expander(f"🏢 {res['Entreprise']} ({res['SIRET']})", expanded=True):
            graph_data = []
            for d, info in res['Domaines'].items():
                c_code = "#28a745" if info['status_rge'] else "#dc3545"
                for h in info['historique']:
                    is_valide = h['lien_debut_regle'] <= date_eng <= h['fin'] if 'lien_debut_regle' in h else h['debut'] <= date_eng <= h['fin']

                    graph_data.append({
                        "Domaine": f"<span style='color:{c_code}'>{d}</span>", 
                        "Début": h['debut'], 
                        "Fin": h['fin'], 
                        "Statut": "Valide" if is_valide else "Expiré"
                    })

            liste_doms, nb_key = list(res['Domaines'].keys()), f"nb_{res['SIRET']}"
            if nb_key not in st.session_state: st.session_state[nb_key] = 1

            for i in range(st.session_state[nb_key]):
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.8, 0.8, 1.2, 0.8, 1.2, 0.6, 0.3])
                with c1: dom_sel = st.selectbox(f"D{i}", options=liste_doms, key=f"s_{res['SIRET']}_{i}", label_visibility="collapsed")
                
                # On récupère les infos arbitrées pour ce domaine précis choisi par l'utilisateur
                info = res['Domaines'][dom_sel]
                
                with c2: 
                    if info['status_rge']: st.success("✅ Valide")
                    else: st.error("❌ Expiré")
                
                # --- CALCUL DE LA PÉRIODE CONSOLIDÉE (BLOC CONTINU) ---
                debut_affiche = info['debut']
                fin_affiche = info['fin']

                if info['status_rge']:
                    from datetime import timedelta
                    # 1. Trier tout l'historique de ce domaine par date de début
                    hist_trie = sorted(info['historique'], key=lambda x: x['lien_debut_regle'])

                    # 2. Algorithme de fusion (on regroupe les périodes espacées de 31 jours ou moins)
                    blocs = []
                    bloc_actuel = [hist_trie[0]['lien_debut_regle'], hist_trie[0]['fin']]

                    for h in hist_trie[1:]:
                        if h['lien_debut_regle'] <= bloc_actuel[1] + timedelta(days=31):
                            # Si ça se suit, on étend la date de fin du bloc
                            bloc_actuel[1] = max(bloc_actuel[1], h['fin'])
                        else:
                            # S'il y a une vraie cassure, on sauvegarde le bloc et on en commence un nouveau
                            blocs.append(bloc_actuel)
                            bloc_actuel = [h['lien_debut_regle'], h['fin']]
                    blocs.append(bloc_actuel)

                    # 3. Trouver le bloc consolidé qui encadre notre date d'engagement
                    for b in blocs:
                        if b[0] <= date_eng <= b[1]:
                            debut_affiche = b[0]
                            fin_affiche = b[1]
                            break

                with c3:
                    st.markdown(
                        f"""
                        <div class='certif-info'>
                            <b>N° Certificat :</b> {info['n_certif']}<br>
                            <i>Début : {debut_affiche.strftime('%d/%m/%Y')}</i><br>
                            <i>Fin : {fin_affiche.strftime('%d/%m/%Y')}</i>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                with c4: choix_bar = st.selectbox("F", options=get_cee_options(dom_sel), key=f"b_{res['SIRET']}_{dom_sel}_{i}", label_visibility="collapsed")
                with c5:
                    if info['url']:
                        try:
                            # Téléchargement du contenu du PDF (arbitré par l'algorithme de distance)
                            content = requests.get(info['url'], timeout=5).content
                            ent_clean = res['Entreprise'].replace(" ", "_").replace("/", "-")
                            
                            # Téléchargement individuel : NOM_FICHE-RGE-OK/KO.pdf
                            ok_ko = "OK" if info['status_rge'] else "KO"
                            nom_indiv = f"{choix_bar}-RGE-{ok_ko} ({ent_clean}).pdf"
                            
                            # Téléchargement ZIP : DOMAINE-ENTREPRISE-STATUT.pdf
                            statut_txt = "VALIDE" if info['status_rge'] else "EXPIRE"
                            nom_zip = f"{dom_sel}-{ent_clean}-{statut_txt}.pdf"
                            
                            st.download_button("📥 Télécharger le certificat", content, nom_indiv, "application/pdf", key=f"dl_{res['SIRET']}_{i}")
                            
                            # MODIFICATION ICI : On s'assure d'ajouter au ZIP exactement le même contenu 
                            # et le nommage associé au domaine et certificat sélectionné à cet instant "i"
                            files_to_zip.append({"content": content, "nom": nom_zip})
                        except: st.caption("⚠️")
                with c6: show_g = st.checkbox("📊 Graph", key=f"check_{res['SIRET']}_{i}")
                with c7:
                    if i == st.session_state[nb_key] - 1:
                        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
                        if st.button("➕", key=f"add_{res['SIRET']}"):
                            st.session_state[nb_key] += 1
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                    elif st.session_state[nb_key] > 1:
                        if st.button("🗑️", key=f"del_{res['SIRET']}_{i}"):
                            st.session_state[nb_key] -= 1
                            st.rerun()

                if show_g and graph_data:
                    df_g = pd.DataFrame(graph_data)
                    df_g["Début"], df_g["Fin"] = pd.to_datetime(df_g["Début"]), pd.to_datetime(df_g["Fin"])
                    fig = px.timeline(df_g, x_start="Début", x_end="Fin", y="Domaine", color="Statut", color_discrete_map={"Valide": "#28a745", "Expiré": "#dee2e6"})
                    fig.add_vline(x=pd.to_datetime(date_eng).timestamp() * 1000, line_dash="dash", line_color="blue")
                    fig.update_layout(barcornerradius=10, height=max(180, (len(df_g["Domaine"].unique()) * 30) + 80), margin=dict(l=0, r=0, t=30, b=60),
                                      yaxis={'title': None, 'tickfont': {'size': 10}}, xaxis={'visible': True, 'tickfont': {'size': 9}},
                                      legend=dict(orientation="h", yanchor="bottom", y=-0.4, xanchor="center", x=0.5))
                    st.plotly_chart(fig, use_container_width=True, key=f"fig_global_{res['SIRET']}_{i}")

                excel_data.append({
                    "SIRET": res['SIRET'], 
                    "Entreprise": res['Entreprise'], 
                    "Domaine": dom_sel, 
                    "Fiche": choix_bar, 
                    "Certificat": info['n_certif'], 
                    "Date de début": info['debut'].strftime('%d/%m/%Y'),
                    "Date de fin": info['fin'].strftime('%d/%m/%Y'),
                    "RGE": "Valide" if info['status_rge'] else "Expiré"
                })

    # --- SÉCURITÉ ANTI-DUPLICATES DANS LE ZIP ---
    if excel_data:
        st.divider()
        cz, ce = st.columns(2)
        with cz:
            if st.button("📦 ZIP des certificats", use_container_width=True) and files_to_zip:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as zf:
                    noms_utilises = set()
                    for f in files_to_zip: 
                        # Si l'utilisateur a plusieurs lignes identiques, on évite de faire crasher le ZIP 
                        # en ajoutant un suffixe numérique si le nom existe déjà
                        nom_final = f['nom']
                        compteur = 1
                        while nom_final in noms_utilises:
                            nom_base, ext = f['nom'].rsplit('.', 1)
                            nom_final = f"{nom_base}_{compteur}.{ext}"
                            compteur += 1
                        
                        noms_utilises.add(nom_final)
                        zf.writestr(nom_final, f['content'])
                st.download_button("⬇️ Télécharger ZIP", buf.getvalue(), "Certificats.zip", use_container_width=True)
        with ce:
            output = io.BytesIO()
            
            # Conversion du timestamp (ms) en objet date lisible
            if isinstance(date_eng, (int, float)):
                # Si c'est un nombre (timestamp), on le convertit
                date_obj = datetime.fromtimestamp(date_eng / 1000)
            else:
                # Si c'est déjà un objet datetime ou date, on l'utilise tel quel
                date_obj = date_eng
                        
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                workbook = writer.book
                worksheet = workbook.add_worksheet('Données')
                writer.sheets['Données'] = worksheet
                
                # Création du format pour qu'Excel affiche une vraie date
                date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
                
                # Écriture des labels et de la date (B2)
                worksheet.write('A1', 'Date d\'engagement :')
                worksheet.write('B1', date_obj, date_format) 
                
                # Écriture des données à partir de la ligne 4 (startrow=3 correspond à la ligne 4)
                pd.DataFrame(excel_data).to_excel(writer, sheet_name='Données', startrow=1, index=False)
            
            # Nom du fichier dynamique (ex: Export_2023-12-03.xlsx)
            nom_fichier = f"Export_{date_eng}.xlsx"
            
            st.download_button(
                "⬇️ Télécharger Excel", 
                data=output.getvalue(), 
                file_name=nom_fichier, 
                use_container_width=True
            )