import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime
import io
import os
from supabase import create_client, Client
from pypdf import PdfWriter, PdfReader
from PIL import Image

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("Librairie manquante. Installez-la via : pip install streamlit-sortables")
    st.stop()

# --- CONFIGURATION & SETUP ---
st.set_page_config(page_title="Universal CRM", page_icon="🗂️", layout="wide")

@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except:
        st.error("Secrets Supabase manquants. Vérifiez votre fichier .streamlit/secrets.toml")
        st.stop()

supabase = init_connection()

# --- FONCTIONS UTILITAIRES ---

def get_siret_info(siret):
    """Récupère les infos entreprise via l'API Gouv"""
    if not siret: return None
    siret = siret.replace(" ", "")
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={siret}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['results']:
                ent = data['results'][0]
                siege = ent.get('siege', {})
                return {
                    "NOM": ent.get('nom_complet'),
                    "ADRESSE": siege.get('adresse'),
                    "VILLE": siege.get('libelle_commune'),
                    "CP": siege.get('code_postal'),
                    "TVA": ent.get('numero_tva_intracommunautaire')
                }
    except Exception as e:
        print(f"Erreur API: {e}")
    return None

def upload_file_to_supabase(file, path):
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(
            path=path,
            file=file_bytes,
            file_options={"content-type": file.type, "upsert": "true"}
        )
        return supabase.storage.from_("fichiers").get_public_url(path)
    except Exception as e:
        st.error(f"Erreur upload: {e}")
        return None

def merge_files_to_pdf(files_urls):
    merger = PdfWriter()
    for url in files_urls:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                file_content = io.BytesIO(response.content)
                if url.lower().endswith(".pdf"):
                    merger.append(PdfReader(file_content))
                elif url.lower().endswith((".png", ".jpg", ".jpeg")):
                    img = Image.open(file_content).convert('RGB')
                    img_pdf = io.BytesIO()
                    img.save(img_pdf, format='PDF')
                    img_pdf.seek(0)
                    merger.append(PdfReader(img_pdf))
        except:
            pass
    output = io.BytesIO()
    merger.write(output)
    output.seek(0)
    return output

# --- INTERFACE ---

st.title("🗂️ Universal CRM & GED")

tab1, tab2, tab3 = st.tabs(["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers", "3. ⚙️ Configuration (Admin)"])

# ==========================================
# ONGLET 1 : NOUVEAU DOSSIER
# ==========================================
with tab1:
    st.header("Créer un nouveau dossier")
    
    activities = supabase.table("activities").select("*").execute().data
    if not activities:
        st.info("Configurez d'abord une Activité dans l'onglet Admin.")
    else:
        act_choice = st.selectbox("Activité", options=[a['name'] for a in activities], key="new_act")
        act_id = next(a['id'] for a in activities if a['name'] == act_choice)
        
        collections = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        
        if collections:
            col_choice = st.selectbox("Modèle", options=[c['name'] for c in collections], key="new_col")
            selected_collection = next(c for c in collections if c['name'] == col_choice)
            fields_config = selected_collection['fields']
            
            st.markdown("---")

            # --- 1. ZONE DE PRÉ-REMPLISSAGE (AUTO-FILL) ---
            has_siret = any(f['type'] == "SIRET" for f in fields_config)
            
            if has_siret:
                with st.container():
                    st.markdown("##### ⚡ Remplissage Rapide")
                    c_search, c_btn = st.columns([3, 1])
                    search_siret = c_search.text_input("Entrez le SIRET pour pré-remplir", placeholder="Ex: 123 456 789 00012", label_visibility="collapsed")
                    
                    if c_btn.button("🔍 Rechercher & Remplir"):
                        infos = get_siret_info(search_siret)
                        if infos:
                            # Injection des données avec clé sécurisée par INDEX
                            # On utilise enumerate(i) pour matcher parfaitement la boucle du formulaire
                            for i, f_target in enumerate(fields_config):
                                t_name = f_target['name'].lower()
                                # CLÉ SÉCURISÉE AVEC INDEX 'i'
                                t_key = f"field_{selected_collection['id']}_{i}_{f_target['name']}"
                                
                                val_to_set = None
                                
                                # Filtres stricts
                                if any(x in t_name for x in ["prénom", "prenom", "contact", "gérant"]):
                                    continue 
                                
                                if any(x in t_name for x in ["société", "societe", "entreprise", "raison sociale", "etablissement"]):
                                    val_to_set = infos['NOM']
                                elif "nom" in t_name and ("ent" in t_name or "soc" in t_name): 
                                    val_to_set = infos['NOM']
                                elif "adresse" in t_name or "rue" in t_name or "siège" in t_name:
                                    val_to_set = infos['ADRESSE']
                                elif "ville" in t_name or "commune" in t_name:
                                    val_to_set = infos['VILLE']
                                elif "cp" in t_name or "postal" in t_name:
                                    val_to_set = infos['CP']
                                elif "tva" in t_name:
                                    val_to_set = infos['TVA']
                                elif f_target['type'] == "SIRET":
                                    val_to_set = search_siret

                                if val_to_set:
                                    # Mise à jour sécurisée
                                    st.session_state[t_key] = val_to_set
                            
                            st.success(f"Données trouvées pour : {infos['NOM']}")
                        else:
                            st.error("SIRET introuvable.")
            
            # --- 2. LE FORMULAIRE DE SAISIE ---
            with st.form("new_record_form"):
                st.subheader("Détails du dossier")
                form_data = {}
                uploaded_files_map = {} 
                
                # IMPORTANT : On utilise enumerate(i) pour garantir l'unicité des clés
                for i, field in enumerate(fields_config):
                    label = field['name']
                    ftype = field['type']
                    required = field.get('required', False)
                    display_label = f"{label} *" if required else label
                    
                    # CLÉ UNIQUE INFAILLIBLE : ID_Collection + Index_Boucle + Nom
                    widget_key = f"field_{selected_collection['id']}_{i}_{label}"

                    if widget_key not in st.session_state:
                         pass

                    if ftype == "Texte Court":
                        form_data[label] = st.text_input(display_label, key=widget_key)
                    elif ftype == "Texte Long":
                        form_data[label] = st.text_area(display_label, key=widget_key)
                    elif ftype == "Nombre":
                        form_data[label] = st.number_input(display_label, step=1.0, key=widget_key)
                    elif ftype == "Date":
                        form_data[label] = st.date_input(display_label, value=None, key=widget_key)
                    elif ftype == "SIRET":
                        form_data[label] = st.text_input(display_label, key=widget_key)
                    elif ftype == "Fichier/Image":
                        uploaded = st.file_uploader(display_label, accept_multiple_files=True, key=widget_key)
                        uploaded_files_map[label] = uploaded
                    elif ftype == "Oui/Non":
                        form_data[label] = st.checkbox(display_label, key=widget_key)
                    else:
                        form_data[label] = st.text_input(display_label, key=widget_key)

                st.markdown("---")
                submit = st.form_submit_button("💾 Enregistrer le Dossier")
                
                if submit:
                    errors = []
                    final_data = form_data.copy()
                    
                    # Validation
                    for field in fields_config:
                        fname = field['name']
                        if field.get('required', False):
                            val = final_data.get(fname)
                            if field['type'] == "Fichier/Image":
                                if not uploaded_files_map.get(fname):
                                    errors.append(f"Champ obligatoire manquant : {fname}")
                            elif not val: 
                                errors.append(f"Champ obligatoire manquant : {fname}")

                    if errors:
                        for e in errors:
                            st.error(e)
                    else:
                        timestamp = int(datetime.now().timestamp())
                        for field in fields_config:
                            if field['type'] == "Fichier/Image":
                                flist = uploaded_files_map.get(field['name'])
                                urls = []
                                if flist:
                                    for f in flist:
                                        path = f"{selected_collection['id']}/{timestamp}_{f.name}"
                                        url = upload_file_to_supabase(f, path)
                                        if url:
                                            urls.append(url)
                                final_data[field['name']] = urls

                        for k, v in final_data.items():
                            if isinstance(v, (datetime, pd.Timestamp)):
                                final_data[k] = v.isoformat()

                        supabase.table("records").insert({
                            "collection_id": selected_collection['id'],
                            "data": final_data
                        }).execute()
                        
                        st.success("Dossier enregistré !")
                        
                        # Nettoyage propre
                        for key in list(st.session_state.keys()):
                            if key.startswith(f"field_{selected_collection['id']}"):
                                del st.session_state[key]
                                
                        st.balloons()
                        st.rerun()

# ==========================================
# ONGLET 2 : GESTION
# ==========================================
with tab2:
    st.header("Gestion des Dossiers")
    all_cols = supabase.table("collections").select("id, name, fields").execute().data
    if all_cols:
        filter_col = st.selectbox("Filtrer par Modèle", ["Tous"] + [c['name'] for c in all_cols])
        query = supabase.table("records").select("*, collections(name, fields)")
        if filter_col != "Tous":
            query = query.eq("collections.name", filter_col)
        records = query.execute().data
        
        if records:
            df_display = []
            for r in records:
                row = r['data'].copy()
                row['ID'] = r['id']
                row['Modèle'] = r['collections']['name']
                row['Date'] = r['created_at'][:10]
                df_display.append(row)
            
            st.dataframe(pd.DataFrame(df_display).set_index("ID"))
            st.divider()
            
            selected_id = st.number_input("ID du dossier à gérer", min_value=0, step=1)
            if selected_id in [r['id'] for r in records]:
                record = next(r for r in records if r['id'] == selected_id)
                rec_data = record['data']
                col_config = record['collections']['fields']
                
                st.subheader(f"Dossier #{selected_id}")
                st.json(rec_data, expanded=False)
                
                if st.button("📥 Télécharger PDF Complet"):
                    blocking_errors = []
                    files_to_merge = []
                    for field in col_config:
                        fname = field['name']
                        if field['type'] == "Fichier/Image":
                            existing = rec_data.get(fname, [])
                            if field.get('required_for_pdf', False) and not existing:
                                blocking_errors.append(f"❌ Document manquant : {fname}")
                            if existing:
                                files_to_merge.extend(existing)

                    if blocking_errors:
                        for err in blocking_errors:
                            st.error(err)
                    elif not files_to_merge:
                        st.warning("Aucun fichier.")
                    else:
                        with st.spinner("Fusion..."):
                            pdf_bytes = merge_files_to_pdf(files_to_merge)
                            st.download_button("💾 Télécharger le PDF", pdf_bytes, f"Dossier_{selected_id}.pdf", "application/pdf")
        else:
            st.info("Aucun dossier.")

# ==========================================
# ONGLET 3 : CONFIGURATION (ADMIN)
# ==========================================
with tab3:
    st.header("⚙️ Configuration")
    
    # 1. Activité
    with st.expander("1. Créer Activité"):
        new_act = st.text_input("Nom Activité")
        if st.button("Créer"):
            supabase.table("activities").insert({"name": new_act}).execute()
            st.rerun()

    st.divider()
    
    # 2. Modèle
    with st.expander("2. Créer Modèle"):
        acts = supabase.table("activities").select("*").execute().data
        if acts:
            target_act = st.selectbox("Lier à", [a['name'] for a in acts])
            act_id = next(a['id'] for a in acts if a['name'] == target_act)
            new_col = st.text_input("Nom Modèle")
            
            if "fields_temp" not in st.session_state:
                st.session_state.fields_temp = []
            
            c1, c2, c3 = st.columns([3, 2, 1])
            f_name = c1.text_input("Nom Champ")
            f_type = c2.selectbox("Type", ["Texte Court", "Texte Long", "Nombre", "Date", "SIRET", "Fichier/Image", "Oui/Non"])
            
            req = st.checkbox("Obligatoire (Saisie)")
            req_pdf = st.checkbox("Bloquant PDF") if f_type == "Fichier/Image" else False
            
            if c3.button("Ajouter"):
                st.session_state.fields_temp.append({
                    "name": f_name, "type": f_type, "required": req, "required_for_pdf": req_pdf
                })
                st.rerun()
            
            if st.session_state.fields_temp:
                st.write("Aperçu :")
                for f in st.session_state.fields_temp:
                    st.text(f"- {f['name']} ({f['type']})")
                if st.button("Reset"):
                    st.session_state.fields_temp = []
                    st.rerun()
            
            if st.button("Sauvegarder Modèle"):
                supabase.table("collections").insert({
                    "name": new_col, "activity_id": act_id, "fields": st.session_state.fields_temp
                }).execute()
                st.success("Créé !")
                st.session_state.fields_temp = []
                st.rerun()

    st.divider()

    # 3. GESTION COMPLETE
    with st.expander("3. Modifier / Réorganiser Modèles", expanded=True):
        acts_m = supabase.table("activities").select("*").execute().data
        if acts_m:
            c_f1, c_f2 = st.columns(2)
            act_choice_m = c_f1.selectbox("Activité", [a['name'] for a in acts_m], key="m_act")
            act_id_m = next(a['id'] for a in acts_m if a['name'] == act_choice_m)
            
            cols_m = supabase.table("collections").select("*").eq("activity_id", act_id_m).execute().data
            if cols_m:
                col_choice_m = c_f2.selectbox("Modèle", [c['name'] for c in cols_m], key="m_col")
                sel_col = next(c for c in cols_m if c['name'] == col_choice_m)
                
                st.write("### ↕️ 1. Organisation")
                original_fields = sel_col['fields']
                field_names = [f['name'] for f in original_fields]
                sorted_names = sort_items(field_names)
                
                # Reconstruction liste
                sorted_fields = []
                for name in sorted_names:
                    obj = next((f for f in original_fields if f['name'] == name), None)
                    if obj: sorted_fields.append(obj)
                
                # --- B. MODIFICATION CHAMPS EXISTANTS ---
                st.divider()
                st.write("### 🔧 2. Options des champs")
                
                final_fields_config = []
                has_changes = False
                if sorted_names != field_names: has_changes = True

                fields_to_keep = [] 
                
                # IMPORTANT : enumerate(i) pour les clés uniques aussi ici
                for idx, field in enumerate(sorted_fields):
                    delete_key = f"del_{sel_col['id']}_{idx}"
                    
                    with st.container():
                        c_del, c_n, c_t, c_o1, c_o2 = st.columns([1, 3, 2, 2, 2])
                        
                        is_deleted = c_del.checkbox("🗑️", key=delete_key, help="Supprimer")
                        
                        if not is_deleted:
                            c_n.text(f"{field['name']}")
                            c_t.caption(f"Type: {field['type']}")
                            
                            new_req = c_o1.checkbox("Obligatoire", value=field.get('required', False), key=f"r_{sel_col['id']}_{idx}")
                            
                            new_pdf = False
                            if field['type'] == "Fichier/Image":
                                new_pdf = c_o2.checkbox("Bloquant PDF", value=field.get('required_for_pdf', False), key=f"p_{sel_col['id']}_{idx}")
                            
                            u_field = field.copy()
                            if new_req != field.get('required', False):
                                u_field['required'] = new_req
                                has_changes = True
                            if field['type'] == "Fichier/Image" and new_pdf != field.get('required_for_pdf', False):
                                u_field['required_for_pdf'] = new_pdf
                                has_changes = True
                            
                            fields_to_keep.append(u_field)
                        else:
                            has_changes = True 
                            st.caption(f"⚠️ Sera supprimé.")
                        
                        st.divider()

                # --- C. AJOUT DE NOUVEAU CHAMP ---
                st.write("### ➕ 3. Ajouter un champ")
                with st.container():
                    c_add1, c_add2, c_add3 = st.columns([3, 2, 2])
                    new_f_name = c_add1.text_input("Nom", key="add_new_name")
                    new_f_type = c_add2.selectbox("Type", ["Texte Court", "Texte Long", "Nombre", "Date", "SIRET", "Fichier/Image", "Oui/Non"], key="add_new_type")
                    
                    if c_add3.button("Ajouter"):
                        if new_f_name:
                            new_field_obj = {
                                "name": new_f_name,
                                "type": new_f_type,
                                "required": False,
                                "required_for_pdf": False
                            }
                            fields_to_keep.append(new_field_obj)
                            has_changes = True
                            supabase.table("collections").update({"fields": fields_to_keep}).eq("id", sel_col['id']).execute()
                            st.success("Ajouté !")
                            st.rerun()

                st.markdown("---")
                if st.button("💾 Enregistrer TOUT"):
                    if has_changes:
                        supabase.table("collections").update({"fields": fields_to_keep}).eq("id", sel_col['id']).execute()
                        st.success("Mis à jour !")
                        st.rerun()
                    else:
                        st.info("Aucun changement.")
                
                with st.expander("Zone Danger"):
                    if st.button("❌ Supprimer le Modèle"):
                        supabase.table("collections").delete().eq("id", sel_col['id']).execute()
                        st.error("Modèle supprimé.")
                        st.rerun()
