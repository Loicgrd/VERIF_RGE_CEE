import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
import requests
import io
import zipfile
import plotly.express as px
import streamlit.components.v1 as components
import os
from streamlit_paste_button import paste_image_button

# --- IMPORT DU NOUVEAU CERVEAU ---
from core.rge_api import get_cee_options, fetch_ademe_data, clean_url, fetch_gouv_data
from core.rge_validite import analyser_lignes, VALIDE, A_VERIFIER, EXPIRE
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
def get_ademe_api_cached(siret):
    """Met en cache les réponses de l'API ADEME pendant 1h (les échecs ne sont pas mis en cache)."""
    lignes, source, limite = fetch_ademe_data(siret, force_local=False)
    if source != "api":
        raise ConnectionError("API ADEME injoignable")
    return lignes


def get_ademe_data(siret, force_local_flag):
    """(lignes, source, date_limite). Le secours local n'est jamais mis en cache."""
    if not force_local_flag:
        try:
            return get_ademe_api_cached(siret), "api", None
        except Exception:
            pass
    return fetch_ademe_data(siret, force_local=True)


# --- SAISIE UTILISATEUR ---
# Indispensable pour pouvoir modifier dynamiquement la date et le tableau
if 'siret_rows' not in st.session_state:
    st.session_state.siret_rows = pd.DataFrame([{"SIRET": ""}], dtype=str)
# Date extraite par l'IA : appliquée AVANT la création du widget (sinon Streamlit l'ignore)
if 'date_eng_pending' in st.session_state:
    st.session_state.date_eng = st.session_state.pop('date_eng_pending')
if 'date_eng' not in st.session_state:
    st.session_state.date_eng = date.today()

c_date, c_upload = st.columns([1, 2])

with c_date:
    date_eng = st.date_input("Date d'engagement :", key="date_eng", format="DD/MM/YYYY")

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
                    st.session_state.date_eng_pending = extracted_date_or_time.date() if isinstance(extracted_date_or_time, datetime) else extracted_date_or_time
                    st.rerun()
                else:
                    date_str = extracted_date_or_time.strftime('%d/%m/%Y')
                    st.success(f"✅ {len(extracted_sirets)} SIRET(s) et date du {date_str} extraits avec succès !")
                    st.session_state.siret_rows = pd.DataFrame([{"SIRET": s} for s in extracted_sirets])
                    st.session_state.date_eng_pending = extracted_date_or_time.date() if isinstance(extracted_date_or_time, datetime) else extracted_date_or_time 
                    st.rerun()

# Affichage du tableau de SIRETs éditable
df_saisie = st.data_editor(
    st.session_state.siret_rows, 
    num_rows="dynamic", 
    width="stretch",
    column_config={"SIRET": st.column_config.TextColumn("SIRET", max_chars=14)}
)

if st.button("🔍 Analyser les SIRET", type="primary"):
    # ✅ CORRECTION : On lit directement df_saisie (valeur du widget au moment du clic),
    # sans passer par session_state qui peut être en retard d'un rerun.
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
                
                # 2. Requête API ADEME (secours local si injoignable)
                api_lines, source, date_limite = get_ademe_data(s, force_local)

                if api_lines:
                    nom_ent = gouv_data.get("nom") if gouv_data.get("trouve") else (api_lines[0].get('nom_entreprise') or api_lines[0].get('raison_sociale') or "Inconnu")
                else:
                    nom_ent = gouv_data.get("nom") if (gouv_data.get("trouve") or gouv_data.get("erreur_siret")) else "Introuvable"
                all_results.append({
                    "SIRET": s,
                    "Entreprise": nom_ent,
                    "lignes": api_lines,
                    "source": source,
                    "date_limite": date_limite,
                    "is_rge": bool(api_lines),
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
            # Statut recalculé à chaque affichage avec la date d'engagement COURANTE
            domaines = analyser_lignes(res['lignes'], date_eng, res.get('date_limite'))

            if res.get('source') == 'local':
                lim = res.get('date_limite')
                st.warning(f"🗄️ Base ADEME injoignable ou mode local : données de la sauvegarde du "
                           f"{lim.strftime('%d/%m/%Y') if lim else 'date inconnue'}. "
                           f"Toute date d'engagement postérieure est « À vérifier ».")

            if gouv.get('date_fermeture'):
                try:
                    d_ferm_gouv = datetime.strptime(gouv['date_fermeture'], '%Y-%m-%d').date()
                    if d_ferm_gouv < date_eng:
                        st.error(f"🔴 Cet établissement était fermé à la date d'engagement (fermé le {d_ferm_gouv.strftime('%d/%m/%Y')}).")
                except ValueError:
                    pass

            LIBELLES = {VALIDE: "Valide", A_VERIFIER: "À vérifier", EXPIRE: "Expiré"}
            graph_data = []
            for d, info in domaines.items():
                c_code = {VALIDE: "#28a745", A_VERIFIER: "#fd7e14", EXPIRE: "#dc3545"}[info['statut']]
                for deb, fin in info['intervalles']:
                    graph_data.append({
                        "Domaine": f"<span style='color:{c_code}'>{d}</span>",
                        "Début": deb,
                        "Fin": min(fin, date.today() + timedelta(days=3650)),
                        "Statut": "Valide" if deb <= date_eng <= fin else "Hors période"
                    })

            liste_doms = list(domaines.keys())
            nb_key = f"nb_{res['SIRET']}"
            if nb_key not in st.session_state: st.session_state[nb_key] = 1

            if not liste_doms:
                st.error("❌ Lignes ADEME présentes mais inexploitables (dates manquantes) : vérifier manuellement.")

            for i in range(st.session_state[nb_key]):
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.5, 0.8, 1.2, 0.8, 1.2, 1.0, 0.5])

                # S'assurer qu'il y a bien des domaines pour éviter une erreur
                if liste_doms:
                    with c1: dom_sel = st.selectbox(f"D{i}", options=liste_doms, key=f"s_{res['SIRET']}_{i}", label_visibility="collapsed")

                    info = domaines[dom_sel]
                    statut = info['statut']
                    debut_affiche, fin_affiche = info['debut'], info['fin']

                    with c2:
                        if statut == VALIDE: st.success("✅ Valide")
                        elif statut == A_VERIFIER: st.warning("⚠️ À vérifier")
                        else: st.error("❌ Expiré")

                    with c3:
                        fin_txt = fin_affiche.strftime('%d/%m/%Y') if fin_affiche and fin_affiche.year < 9999 else "—"
                        deb_txt = debut_affiche.strftime('%d/%m/%Y') if debut_affiche else "—"
                        motif_html = f"<br><small>⚠️ {info['motif']}</small>" if info['motif'] else ""
                        st.markdown(f"<div class='certif-info'><b>N° Certificat :</b> {info['n_certif']}<br><i>Début : {deb_txt}</i><br><i>Fin : {fin_txt}</i>{motif_html}</div>", unsafe_allow_html=True)

                    with c4: choix_bar = st.selectbox("F", options=get_cee_options(dom_sel), key=f"b_{res['SIRET']}_{dom_sel}_{i}", label_visibility="collapsed")
                    
                    with c5:
                        url_cert = clean_url(info['url'])
                        if url_cert:
                            st.link_button("👁️ Voir certificat", url_cert)
                            try:
                                content = get_pdf_content(url_cert)
                                
                                if content:
                                    ent_clean = res['Entreprise'].replace(" ", "_").replace("/", "-")
                                    ok_ko = {VALIDE: "OK", A_VERIFIER: "A-VERIFIER", EXPIRE: "KO"}[statut]
                                    nom_indiv = f"{choix_bar}-RGE-{ok_ko} ({ent_clean}).pdf"
        
                                    statut_txt = {VALIDE: "VALIDE", A_VERIFIER: "A-VERIFIER", EXPIRE: "EXPIRE"}[statut]
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
                        fig = px.timeline(df_g, x_start="Début", x_end="Fin", y="Domaine", color="Statut", color_discrete_map={"Valide": "#28a745", "Hors période": "#dee2e6"})
                        fig.update_traces(hovertemplate="<b>%{y}</b><br>Début : %{base|%d/%m/%Y}<br>Fin : %{x|%d/%m/%Y}<extra></extra>")
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

                    # ✅ CORRECTION 2 : Un seul excel_data.append() par ligne (le doublon a été supprimé)
                    excel_data.append({
                        "SIRET": res['SIRET'], 
                        "Entreprise": res['Entreprise'], 
                        "Domaine": dom_sel, 
                        "Fiche": choix_bar, 
                        "Certificat": info['n_certif'], 
                        "Date de début": debut_affiche,
                        "Date de fin": fin_affiche,
                        "RGE": LIBELLES[statut],
                        "Motif": info['motif'],
                        "Source": "ADEME (direct)" if res.get('source') == 'api' else f"Sauvegarde locale du {res['date_limite'].strftime('%d/%m/%Y') if res.get('date_limite') else '?'}"
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
                worksheet.set_column('F:G', 15) # Permet d'agrandir les colonnes dates
                worksheet.write('A1', 'Date d\'engagement :')
                worksheet.write('B1', date_obj, date_format) 
                pd.DataFrame(excel_data).to_excel(writer, sheet_name='Données', startrow=1, index=False)
            
            nom_fichier = f"Export_{date_eng}.xlsx"
            st.download_button("⬇️ Télécharger Excel", data=output.getvalue(), file_name=nom_fichier, width="stretch")
