import streamlit as st
import pandas as pd
from datetime import datetime
import requests
import io
import zipfile
import plotly.express as px
import streamlit.components.v1 as components
import os
from streamlit_paste_button import paste_image_button

# --- IMPORT DU NOUVEAU CERVEAU ---
from core.rge_api import get_cee_options, fetch_ademe_data, extract_qualif_code, clean_url, fetch_gouv_data
from core.ia_extraction import analyze_documents


# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Vérification des RGE", layout="wide")

c1, c2 = st.columns([0.9, 0.1])

with c1:
    st.title("🔍 Vérification des RGE")

with c2:
    force_local = st.toggle(
        "🗄️ Local", 
        value=False,
        help="Forcer la base de données locale en cas de bug ou ralentissement de l'ADEME"
    )

# --- STYLE CSS ---
st.html("""
<style>
    [data-testid="stFileUploadDropzone"] {
        min-height: 40px !important;
        height: 40px !important;
        padding: 0px !important;
    }
</style>
""")

# --- OPTIMISATION : MISE EN CACHE DES REQUÊTES LOURDES ---
@st.cache_data(show_spinner=False)
def get_pdf_content(url):
    """Télécharge le PDF une seule fois et le garde en mémoire."""
    try:
        return requests.get(url, timeout=5).content
    except Exception:
        return None

@st.cache_data(show_spinner=False, ttl=3600)
def get_gouv_data_cached(siret):
    """Met en cache les requêtes gouvernementales pendant 1h."""
    return fetch_gouv_data(siret)

@st.cache_data(show_spinner=False, ttl=3600)
def get_ademe_data_cached(siret, force_local_flag):
    """Met en cache les requêtes ADEME pendant 1h."""
    return fetch_ademe_data(siret, force_local=force_local_flag)


# --- SAISIE UTILISATEUR ---
# Indispensable pour pouvoir modifier dynamiquement la date et le tableau
if 'siret_rows' not in st.session_state:
    st.session_state.siret_rows = pd.DataFrame([{"SIRET": ""}], dtype=str)
if 'date_eng_val' not in st.session_state:
    st.session_state.date_eng_val = datetime.now()

c_date, c_upload = st.columns([1, 2])

with c_date:
    date_eng = st.date_input("Date d'engagement :", value=st.session_state.date_eng_val, format="DD/MM/YYYY")
    st.session_state.date_eng_val = date_eng

with c_upload:
    # 1. Titre global placé au-dessus pour libérer de l'espace horizontal
    st.markdown("**📂 Extraction de données (SIRET, Date d'engagement)**")
    
    # 2. Création de deux colonnes alignées verticalement au centre
    col_file, col_paste = st.columns([3, 1], vertical_alignment="center")
    
    with col_file:
        # Le label_visibility="collapsed" permet de coller le composant en haut de sa colonne
        docs = st.file_uploader(
            "Extraction de données", 
            type=["pdf", "xlsx", "xls", "zip", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            help="Attention : Utilisation d'IA, ne pas importer de documents avec des éléments à caractère confidentiel."
        )
        
    with col_paste:
        # Le bouton vient se placer directement à droite du bloc d'importation
        paste_result = paste_image_button("📋 Coller une capture")
        
    # Liste globale des documents à envoyer à l'analyse
    docs_a_analyser = list(docs) if docs else []
    
    # 3. Message de confirmation ultra-compact à la place de l'affichage de l'image
    if paste_result.image_data is not None:
        st.caption("✨ *Image détectée dans le presse-papiers et prête pour l'analyse*")
        
        # Préparation du flux pour l'API Gemini
        img_buffer = io.BytesIO()
        paste_result.image_data.save(img_buffer, format="PNG")
        img_buffer.name = "image_collee.png" 
        
        docs_a_analyser.append(img_buffer)

    # 4. Lancement de l'analyse si au moins un élément est présent
    if len(docs_a_analyser) > 0:
        if st.button("🧠 Extraire SIRET & Date", type="secondary", width="stretch"):
            with st.spinner("Analyse des documents en cours..."):
                extracted_sirets, extracted_date_or_time = analyze_documents(docs_a_analyser)
                
                # ... (votre suite de traitement des résultats reste identique) ---
                
                # --- GESTION DES RÉSULTATS IA (votre code d'origine reste ici) ---
                if "QUOTA_EXCEEDED" in extracted_sirets:
                    temps_attente = extracted_date_or_time
                    st.warning(f"⏳ Limite de requêtes IA atteinte. Veuillez patienter {temps_attente} secondes avant de réessayer.")
                
                # --- GESTION DES RÉSULTATS IA ---
                if "QUOTA_EXCEEDED" in extracted_sirets:
                    temps_attente = extracted_date_or_time
                    st.warning(f"⏳ Limite de requêtes IA atteinte. Veuillez patienter {temps_attente} secondes avant de réessayer.")
                elif not extracted_date_or_time and not extracted_sirets:
                    st.warning("❌ Aucune donnée exploitable trouvée dans ces documents.")
                elif extracted_sirets and not extracted_date_or_time:
                    st.warning("⚠️ SIRET(s) détecté(s), mais aucune date d'engagement n'a pu être lue de manière fiable.")
                    st.info(f"SIRETs trouvés : {', '.join(extracted_sirets)}. Veuillez saisir la date manuellement pour lancer l'analyse.")
                    st.session_state.siret_rows = pd.DataFrame([{"SIRET": s} for s in extracted_sirets])
                    st.rerun()
                elif extracted_date_or_time and not extracted_sirets:
                    date_str = extracted_date_or_time.strftime('%d/%m/%Y')
                    st.warning(f"⚠️ Date d'engagement trouvée ({date_str}), mais aucun SIRET détecté.")
                    st.info("Veuillez saisir les numéros de SIRET manuellement pour continuer.")
                    st.session_state.date_input_key = extracted_date_or_time
                    st.rerun()
                else:
                    date_str = extracted_date_or_time.strftime('%d/%m/%Y')
                    st.success(f"✅ {len(extracted_sirets)} SIRET(s) et date du {date_str} extraits avec succès !")
                    st.session_state.siret_rows = pd.DataFrame([{"SIRET": s} for s in extracted_sirets])
                    st.session_state.date_input_key = extracted_date_or_time 
                    st.rerun()

# Affichage du tableau de SIRETs éditable
df_saisie = st.data_editor(
    st.session_state.siret_rows, 
    num_rows="dynamic", 
    width="stretch",
    column_config={"SIRET": st.column_config.TextColumn("SIRET", max_chars=14)}
)

if st.button("🔍 Analyser les SIRET", type="primary"):
    sirets = [str(s).strip() for s in df_saisie["SIRET"] if s and str(s).strip()]
    if not sirets:
        st.warning("Veuillez saisir au moins un SIRET.")
    else:
        if 'audit_results' in st.session_state:
            del st.session_state.audit_results
        all_results = []
        with st.spinner("Analyse ADEME et Gouvernement..."):
            for s in sirets:
                # 1. Requête API Gouvernement (Mise en cache)
                gouv_data = get_gouv_data_cached(s)
                
                # 2. Requête API ADEME (Mise en cache)
                api_lines = get_ademe_data_cached(s, force_local)
                
                if api_lines:
                    # ---> L'ENTREPRISE EST RGE
                    nom_ent = gouv_data.get("nom") if gouv_data.get("trouve") else (api_lines[0].get('nom_entreprise') or api_lines[0].get('raison_sociale') or "Inconnu")
                    domaines_raw = {}
                    for line in api_lines:
                        dom = str(line.get('domaine', 'Inconnu')).strip()
                        lien_debut = line.get('lien_date_debut')
                        lien_fin = line.get('lien_date_fin') or line.get('date_fin')
                        tech_debut = line.get('date_debut') or line.get('lien_date_debut')
                        
                        if lien_debut and lien_fin:
                            try:
                                d_lien_debut = datetime.strptime(lien_debut[:10], '%Y-%m-%d').date()
                                d_lien_fin = datetime.strptime(lien_fin[:10], '%Y-%m-%d').date()
                                d_tech_debut = datetime.strptime(tech_debut[:10], '%Y-%m-%d').date()
                                
                                if dom not in domaines_raw: 
                                    domaines_raw[dom] = []
                                    
                                domaines_raw[dom].append({
                                    "n_certif": extract_qualif_code(line.get('_id', "N/A")), 
                                    "debut": d_lien_debut,
                                    "fin": d_lien_fin,
                                    "lien_debut_regle": d_lien_debut,
                                    "tech_debut_score": d_tech_debut,
                                    "url": clean_url(line.get('url_qualification') or line.get('lien_certificat'))
                                })
                            except: 
                                continue
                                
                    domaines_finaux = {}
                    for dom, periodes in domaines_raw.items():
                        lignes_valides = [p for p in periodes if p['lien_debut_regle'] <= date_eng <= p['fin']]
                        if lignes_valides:
                            meilleure_ligne = min(lignes_valides, key=lambda x: abs((x['tech_debut_score'] - date_eng).days))
                            domaines_finaux[dom] = {**meilleure_ligne, "status_rge": True, "historique": periodes}
                        else:
                            plus_recente = max(periodes, key=lambda x: x['fin'])
                            domaines_finaux[dom] = {**plus_recente, "status_rge": False, "historique": periodes}
                            
                    all_results.append({
                        "SIRET": s, 
                        "Entreprise": nom_ent, 
                        "Domaines": domaines_finaux,
                        "is_rge": True,
                        "gouv_data": gouv_data
                    })
                else:
                    # ---> L'ENTREPRISE N'EST PAS RGE (ou introuvable)
                    nom_ent = gouv_data.get("nom") if (gouv_data.get("trouve") or gouv_data.get("erreur_siret")) else "Introuvable"
                    all_results.append({
                        "SIRET": s, 
                        "Entreprise": nom_ent, 
                        "Domaines": {},
                        "is_rge": False,
                        "gouv_data": gouv_data
                    })

        if not all_results:
            st.error("❌ Aucun résultat trouvé pour le(s) SIRET saisis.")
        else:
            st.session_state.audit_results = all_results


# --- AFFICHAGE DES RÉSULTATS ---
if 'audit_results' in st.session_state:
    files_to_zip, excel_data = [], []

    for res in st.session_state.audit_results:
        gouv = res.get('gouv_data', {})
        est_rge = res.get("is_rge", False)
        
        # CORRECTION DU BUG : Si l'entreprise est RGE, le SIRET est forcément valide
        erreur_siret = gouv.get("erreur_siret", False) and not est_rge

        # 1. Construction du titre de l'encart
        if erreur_siret:
            titre_expander = f"❌ ERREUR DE SAISIE : SIRET {res['SIRET']} invalide ({res['Entreprise']})"
        else:
            titre_expander = f"🏢 {res['Entreprise']} ({res['SIRET']})"
            
            # Ajout de l'état d'ouverture (Gouv)
            if gouv.get("trouve"):
                d_crea = gouv.get('date_creation')
                d_ferm = gouv.get('date_fermeture')
                etat = gouv.get('etat_admin', 'A')
                
                d_crea_str = datetime.strptime(d_crea, '%Y-%m-%d').strftime('%d/%m/%Y') if d_crea else "?"
                
                if etat == 'F' or d_ferm:
                    d_ferm_str = datetime.strptime(d_ferm, '%Y-%m-%d').strftime('%d/%m/%Y') if d_ferm else "?"
                    titre_expander += f" — 🔴 Fermée (Ouverte le {d_crea_str}, Fermée le {d_ferm_str})"
                else:
                    titre_expander += f" — 🟢 Ouverte depuis le {d_crea_str}"

            # Alerte NON RGE directement dans le titre
            if not est_rge:
                titre_expander += " — ⚠️ ATTENTION : N'EST PAS RGE (Aucune donnée ADEME)"
        
        with st.expander(titre_expander, expanded=True):
            
            # ---> CAS 1 : ENTREPRISE NON RGE
            if not est_rge:
                if gouv.get("trouve"):
                    col_identite, col_statut_adresse, col_agences = st.columns([1, 1.2, 1.5])
                    with col_identite:
                        st.markdown(f"**🏢 {res['Entreprise']}**")
                        st.write(f"SIRET : {res['SIRET']}")
                    with col_statut_adresse:
                        if gouv.get('etat_admin') == 'F' or gouv.get('date_fermeture'):
                            st.error("🔴 Entreprise fermée")
                        else:
                            st.success("🟢 Entreprise en activité")
                        st.write(f"📍 {gouv.get('adresse_complete', 'Inconnue')}")
                    with col_agences:
                        st.warning("⚠️ Aucune certification RGE trouvée pour ce SIRET à l'ADEME.")
                    
                # Prise en charge de l'erreur de NIC
                elif erreur_siret:
                    st.error(f"❌ **Erreur de saisie** : Le SIRET **{res['SIRET']}** n'existe pas.")
                    st.warning(f"💡 Le SIREN correspond bien à l'entreprise **{gouv.get('nom')}**, mais la fin du numéro (le NIC) est incorrecte.")
                    
                    autres = gouv.get('autres_agences', [])
                    if autres:
                        with st.expander(f"📍 Voir les agences valides pour cette entreprise ({len(autres)})", expanded=False):
                            for a in autres:
                                etat_a = a.get('etat_administratif')
                                s_badge = "🔴 Fermée" if etat_a == 'F' else "🟢 Active"
                                
                                d_ouv_raw = a.get('date_creation')
                                d_ferm_raw = a.get('date_fermeture')
                                d_ouv = datetime.strptime(d_ouv_raw, '%Y-%m-%d').strftime('%d/%m/%Y') if d_ouv_raw else "?"
                                
                                if etat_a == 'F' or d_ferm_raw:
                                    d_ferm_a = datetime.strptime(d_ferm_raw, '%Y-%m-%d').strftime('%d/%m/%Y') if d_ferm_raw else "?"
                                    texte_date = f"du {d_ouv} au {d_ferm_a}"
                                else:
                                    texte_date = f"depuis le {d_ouv}"
                                    
                                st.markdown(f"- **{a.get('siret')}** ({a.get('libelle_commune', 'Inconnu')}) : {s_badge} *({texte_date})*")
                
                else:
                    st.error(f"❌ SIRET {res['SIRET']} totalement introuvable (ni RGE, ni dans la base du Gouvernement).")
                
                continue # On passe au SIRET suivant

            # ---> CAS 2 : ENTREPRISE RGE
            graph_data = []
            for d, info in res.get('Domaines', {}).items():
                c_code = "#28a745" if info['status_rge'] else "#dc3545"
                for h in info['historique']:
                    is_valide = h['lien_debut_regle'] <= date_eng <= h['fin'] if 'lien_debut_regle' in h else h['debut'] <= date_eng <= h['fin']
                    graph_data.append({
                        "Domaine": f"<span style='color:{c_code}'>{d}</span>", 
                        "Début": h['debut'], 
                        "Fin": h['fin'], 
                        "Statut": "Valide" if is_valide else "Expiré"
                    })

            liste_doms = list(res.get('Domaines', {}).keys())
            nb_key = f"nb_{res['SIRET']}"
            if nb_key not in st.session_state: st.session_state[nb_key] = 1

            for i in range(st.session_state[nb_key]):
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.5, 0.8, 1.2, 0.8, 1.2, 1.0, 0.5])
                
                # S'assurer qu'il y a bien des domaines pour éviter une erreur
                if liste_doms:
                    with c1: dom_sel = st.selectbox(f"D{i}", options=liste_doms, key=f"s_{res['SIRET']}_{i}", label_visibility="collapsed")
                    
                    info = res['Domaines'][dom_sel]
                    
                    with c2: 
                        if info['status_rge']: st.success("✅ Valide")
                        else: st.error("❌ Expiré")
                    
                    debut_affiche = info['debut']
                    fin_affiche = info['fin']

                    if info['status_rge']:
                        from datetime import timedelta
                        hist_trie = sorted(info['historique'], key=lambda x: x['lien_debut_regle'])
                        blocs = []
                        bloc_actuel = [hist_trie[0]['lien_debut_regle'], hist_trie[0]['fin']]

                        for h in hist_trie[1:]:
                            if h['lien_debut_regle'] <= bloc_actuel[1] + timedelta(days=31):
                                bloc_actuel[1] = max(bloc_actuel[1], h['fin'])
                            else:
                                blocs.append(bloc_actuel)
                                bloc_actuel = [h['lien_debut_regle'], h['fin']]
                        blocs.append(bloc_actuel)

                        for b in blocs:
                            if b[0] <= date_eng <= b[1]:
                                debut_affiche = b[0]
                                fin_affiche = b[1]
                                break

                    with c3:
                        st.markdown(f"<div class='certif-info'><b>N° Certificat :</b> {info['n_certif']}<br><i>Début : {debut_affiche.strftime('%d/%m/%Y')}</i><br><i>Fin : {fin_affiche.strftime('%d/%m/%Y')}</i></div>", unsafe_allow_html=True)
                    
                    with c4: choix_bar = st.selectbox("F", options=get_cee_options(dom_sel), key=f"b_{res['SIRET']}_{dom_sel}_{i}", label_visibility="collapsed")
                    
                    with c5:
                        if info['url']:
                            st.link_button("👁️ Voir certificat", info['url'])
                            try:
                                content = get_pdf_content(info['url'])
                                
                                if content:
                                    ent_clean = res['Entreprise'].replace(" ", "_").replace("/", "-")
                                    ok_ko = "OK" if info['status_rge'] else "KO"
                                    nom_indiv = f"{choix_bar}-RGE-{ok_ko} ({ent_clean}).pdf"
        
                                    statut_txt = "VALIDE" if info['status_rge'] else "EXPIRE"
                                    nom_zip = f"{dom_sel}-{ent_clean}-{statut_txt}.pdf"
                                    st.download_button("📥 Télécharger", content, nom_indiv, "application/pdf", key=f"dl_{res['SIRET']}_{i}")
                                    files_to_zip.append({"content": content, "nom": nom_zip})
                            except: st.caption("⚠️ Erreur téléchargement")
                    
                    with c6: 
                        show_g = st.checkbox("📊 Graph", key=f"check_g_{res['SIRET']}_{i}")
                        show_a = False
                        autres = gouv.get('autres_agences', [])
                        if i == 0 and autres:
                            show_a = st.checkbox(f"📍Agences ({len(autres)})", key=f"check_a_{res['SIRET']}")
                    
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
                        st.plotly_chart(fig, width="stretch", key=f"fig_global_{res['SIRET']}_{i}")

                    if i == 0 and show_a:
                        st.markdown("---")
                        st.markdown(f"**📍 Liste des autres agences liées à cette entreprise ({len(autres)} au total) :**")
                        
                        for a in autres: 
                            etat_a = a.get('etat_administratif')
                            s_badge = "🔴 Fermée" if etat_a == 'F' else "🟢 Active"
                            
                            d_ouv_raw = a.get('date_creation')
                            d_ferm_raw = a.get('date_fermeture')
                            d_ouv = datetime.strptime(d_ouv_raw, '%Y-%m-%d').strftime('%d/%m/%Y') if d_ouv_raw else "?"
                            
                            if etat_a == 'F' or d_ferm_raw:
                                d_ferm_a = datetime.strptime(d_ferm_raw, '%Y-%m-%d').strftime('%d/%m/%Y') if d_ferm_raw else "?"
                                texte_date = f"du {d_ouv} au {d_ferm_a}"
                            else:
                                texte_date = f"depuis le {d_ouv}"
                                
                            st.markdown(f"- **{a.get('siret')}** ({a.get('libelle_commune', 'Inconnu')}) : {s_badge} *({texte_date})*")

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

    if excel_data:
        st.divider()
        cz, ce = st.columns(2)
        with cz:
            if st.button("📦 ZIP des certificats", width="stretch") and files_to_zip:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as zf:
                    noms_utilises = set()
                    for f in files_to_zip: 
                        nom_final = f['nom']
                        compteur = 1
                        while nom_final in noms_utilises:
                            nom_base, ext = f['nom'].rsplit('.', 1)
                            nom_final = f"{nom_base}_{compteur}.{ext}"
                            compteur += 1
                        noms_utilises.add(nom_final)
                        zf.writestr(nom_final, f['content'])
                st.download_button("⬇️ Télécharger ZIP", buf.getvalue(), "Certificats.zip", width="stretch")
        with ce:
            output = io.BytesIO()
            if isinstance(date_eng, (int, float)):
                date_obj = datetime.fromtimestamp(date_eng / 1000)
            else:
                date_obj = date_eng
                        
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                workbook = writer.book
                worksheet = workbook.add_worksheet('Données')
                writer.sheets['Données'] = worksheet
                date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
                worksheet.write('A1', 'Date d\'engagement :')
                worksheet.write('B1', date_obj, date_format) 
                pd.DataFrame(excel_data).to_excel(writer, sheet_name='Données', startrow=1, index=False)
            
            nom_fichier = f"Export_{date_eng}.xlsx"
            st.download_button("⬇️ Télécharger Excel", data=output.getvalue(), file_name=nom_fichier, width="stretch")








