import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import io
import time
import re
from supabase import create_client, Client
from pypdf import PdfWriter, PdfReader
from PIL import Image

# Import Gestion des Cookies
try:
    import extra_streamlit_components as stx
except ImportError:
    st.error("⚠️ Librairie manquante : 'extra-streamlit-components'. Ajoutez-la à requirements.txt")
    st.stop()

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("⚠️ Librairie manquante : 'streamlit-sortables'. Ajoutez-la à requirements.txt")
    st.stop()

# --- CONFIGURATION ---
st.set_page_config(page_title="Universal CRM SaaS", page_icon="🚀", layout="wide")

# --- INITIALISATION SUPABASE ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"] if "SUPABASE_URL" in st.secrets else "URL_MANQUANTE"
        key = st.secrets["SUPABASE_KEY"] if "SUPABASE_KEY" in st.secrets else "KEY_MANQUANTE"
        
        if url == "URL_MANQUANTE":
            st.error("⚠️ Les secrets Supabase (URL/KEY) sont introuvables.")
            st.stop()
            
        return create_client(url, key)
    except Exception as e:
        st.error(f"Erreur technique connexion Supabase : {e}")
        st.stop()

supabase = init_connection()

# --- GESTION DES COOKIES ---
cookie_manager = stx.CookieManager()

# --- GESTION ÉTAT SESSION ---
if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile' not in st.session_state:
    st.session_state.profile = None

if 'form_reset_id' not in st.session_state:
    st.session_state.form_reset_id = 0
if 'upload_reset_id' not in st.session_state:
    st.session_state.upload_reset_id = 0

# --- RECONNEXION AUTO ---
if not st.session_state.user:
    time.sleep(0.1)
    refresh_token = cookie_manager.get("sb_refresh_token")
    if refresh_token:
        try:
            res = supabase.auth.refresh_session(refresh_token)
            if res.user and res.session:
                st.session_state.user = res.user
                profile_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                if profile_data:
                    st.session_state.profile = profile_data[0]
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
                    st.toast("Session restaurée.")
                else:
                    cookie_manager.delete("sb_refresh_token")
        except:
            cookie_manager.delete("sb_refresh_token")

# --- FONCTIONS UTILITAIRES ---

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user = res.user
        profile_data = supabase.table("profiles").select("*").eq("id", user.id).execute().data
        
        if profile_data:
            st.session_state.user = user
            st.session_state.profile = profile_data[0]
            if res.session:
                cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
            st.success("Connexion réussie !")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("Utilisateur authentifié mais aucun profil trouvé.")
            supabase.auth.sign_out()
    except Exception as e:
        st.error(f"Erreur de connexion : {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    time.sleep(0.5)
    st.rerun()

def get_siret_info(siret):
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
    except: pass
    return None

def upload_file(file, path):
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(path, file_bytes, {"content-type": file.type, "upsert": "true"})
        return supabase.storage.from_("fichiers").get_public_url(path)
    except: return None

# --- NOUVELLE FONCTION V24 : FUSION PDF ---
def merge_files_to_pdf(file_urls):
    merger = PdfWriter()
    
    for url in file_urls:
        try:
            # Téléchargement du fichier
            response = requests.get(url)
            if response.status_code == 200:
                f_data = io.BytesIO(response.content)
                
                # Detection basique extension via URL
                lower_url = url.lower()
                
                if lower_url.endswith('.pdf'):
                    reader = PdfReader(f_data)
                    for page in reader.pages:
                        merger.add_page(page)
                        
                elif lower_url.endswith(('.png', '.jpg', '.jpeg')):
                    # Conversion Image -> PDF
                    img = Image.open(f_data)
                    if img.mode == 'RGBA':
                        img = img.convert('RGB')
                    
                    img_pdf_bytes = io.BytesIO()
                    img.save(img_pdf_bytes, format='PDF')
                    img_pdf_bytes.seek(0)
                    
                    reader = PdfReader(img_pdf_bytes)
                    merger.add_page(reader.pages[0])
                    
        except Exception as e:
            print(f"Erreur fusion {url}: {e}")
            continue
            
    output = io.BytesIO()
    merger.write(output)
    return output.getvalue()

# ==========================================
# 🔐 PAGE DE LOGIN
# ==========================================
if not st.session_state.user:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                login(email, password)
    st.stop()

# ==========================================
# 🚀 APPLICATION PRINCIPALE
# ==========================================

if st.session_state.profile is None:
    st.warning("⚠️ Session invalide. Reconnexion requise...")
    logout()
    st.stop()

MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name', 'Utilisateur')}")
    st.caption(f"Rôle : {MY_ROLE}")
    st.divider()
    if st.button("Se déconnecter", use_container_width=True, type="primary"):
        logout()

st.title("Universal CRM SaaS 🚀")

# ------------------------------------------------------------------
# 👑 SUPER ADMIN DASHBOARD
# ------------------------------------------------------------------
if MY_ROLE == "super_admin":
    st.success("👑 Mode Super Admin activé")
    sa_tab1, sa_tab2 = st.tabs(["🏢 Gestion Entreprises", "👀 Accéder au CRM"])
    
    with sa_tab1:
        st.subheader("Créer une nouvelle entreprise")
        with st.form("create_company"):
            c_name = st.text_input("Nom de l'entreprise")
            admin_email = st.text_input("Email de l'Admin principal")
            admin_pass = st.text_input("Mot de passe temporaire (min 6 car.)", type="password")
            submitted = st.form_submit_button("Créer Entreprise & Admin")
            
            if submitted:
                if not c_name or not admin_email or not admin_pass:
                    st.error("❌ Tous les champs sont requis.")
                    st.stop()
                if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", admin_email):
                    st.error("❌ Format d'email invalide.")
                    st.stop()
                if len(admin_pass) < 6:
                    st.warning("⚠️ Mot de passe trop court.")
                    st.stop()

                new_comp_id = None
                new_user_id = None
                try:
                    res_comp = supabase.table("companies").insert({"name": c_name}).execute()
                    if res_comp.data:
                        new_comp_id = res_comp.data[0]['id']
                    else:
                        raise Exception("Erreur DB Entreprise")
                    
                    res_auth = supabase.auth.sign_up({
                        "email": admin_email, "password": admin_pass,
                        "options": {"data": {"full_name": f"Admin {c_name}"}}
                    })
                    
                    if res_auth.user:
                        new_user_id = res_auth.user.id
                    else:
                        raise Exception("Erreur Auth User")

                    supabase.table("profiles").insert({
                        "id": new_user_id, "email": admin_email, "company_id": new_comp_id,
                        "role": "admin", "full_name": f"Admin {c_name}"
                    }).execute()

                    st.success(f"✅ Entreprise '{c_name}' créée !")
                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Erreur : {e}")
                    if new_comp_id:
                        supabase.table("companies").delete().eq("id", new_comp_id).execute()

    with sa_tab2:
        st.write("Sélectionnez une entreprise :")
        all_comps = supabase.table("companies").select("*").execute().data
        comp_map = {c['name']: c['id'] for c in all_comps}
        target_comp_name = st.selectbox("Choisir Entreprise", list(comp_map.keys()))
        if target_comp_name:
            MY_COMPANY_ID = comp_map[target_comp_name]
            st.info(f"👀 Vue sur : **{target_comp_name}**")
            st.divider()

if MY_ROLE == "super_admin" and not MY_COMPANY_ID:
    st.warning("👈 Sélectionnez une entreprise.")
    st.stop()

# ------------------------------------------------------------------
# 🏢 CRM LOGIC
# ------------------------------------------------------------------

tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin", "super_admin"]:
    tabs_list.append("3. ⚙️ Configuration")
    tabs_list.append("4. 👥 Utilisateurs")

tabs = st.tabs(tabs_list)

# ONGLET 1 : NOUVEAU DOSSIER
with tabs[0]:
    st.header("Créer un nouveau dossier")
    activities = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    
    if not activities:
        st.info("⚠️ Aucune activité configurée.")
    else:
        act_choice = st.selectbox("Activité", [a['name'] for a in activities])
        act_id = next(a['id'] for a in activities if a['name'] == act_choice)
        
        collections = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        
        if collections:
            col_choice = st.selectbox("Modèle", [c['name'] for c in collections])
            sel_col = next(c for c in collections if c['name'] == col_choice)
            fields = sel_col['fields']
            
            FORM_ID = st.session_state.form_reset_id
            
            # --- AUTO FILL SIRET ---
            if any(f['type'] == "SIRET" for f in fields):
                with st.expander("⚡ Remplissage SIRET", expanded=True):
                    c_s, c_b = st.columns([3, 1])
                    siret_in = c_s.text_input("SIRET", label_visibility="collapsed", key=f"siret_search_{FORM_ID}")
                    if c_b.button("Remplir"):
                        infos = get_siret_info(siret_in)
                        if infos:
                            for i, f in enumerate(fields):
                                key = f"f_{sel_col['id']}_{i}_{f['name']}_{FORM_ID}"
                                n = f['name'].lower()
                                val = None
                                
                                if f['type'] == 'SIRET': val = siret_in
                                elif any(x in n for x in ["raison sociale", "société", "entreprise", "etablissement"]): val = infos['NOM']
                                elif any(x in n for x in ["adresse", "siège", "kbis"]) and not any(y in n for y in ["travaux", "chantier", "intervention", "installation"]): val = infos['ADRESSE']
                                elif "ville" in n and not any(y in n for y in ["travaux", "chantier", "installation"]): val = infos['VILLE']
                                elif any(x in n for x in ["cp", "code postal"]) and not any(y in n for y in ["travaux", "chantier", "installation"]): val = infos['CP']
                                elif "tva" in n: val = infos['TVA']
                                
                                if val: st.session_state[key] = val
                            st.success("Données chargées !")

            # --- FORMULAIRE DYNAMIQUE ---
            st.divider()
            
            data = {}
            files_map = {}
            main_addr = ""
            
            for i, f in enumerate(fields):
                key = f"f_{sel_col['id']}_{i}_{f['name']}_{FORM_ID}"
                lbl = f"{f['name']} *" if f.get('required') else f['name']
                
                if f['type'] != "Fichier/Image" and key not in st.session_state:
                    st.session_state[key] = ""
                
                if f['type'] == "Section/Titre":
                    st.markdown(f"**{f['name']}**")
                    
                elif f['type'] == "Texte Court":
                    val = st.text_input(lbl, key=key)
                    data[f['name']] = val
                    n_lower = f['name'].lower()
                    if any(x in n_lower for x in ["adresse", "siège", "kbis", "facturation"]) and not any(x in n_lower for x in ["travaux", "chantier", "installation"]):
                        main_addr = val
                    
                elif f['type'] == "Adresse":
                    val = st.text_input(lbl, key=key)
                    data[f['name']] = val
                    main_addr = val 
                    
                elif f['type'] == "Adresse Travaux":
                    use_same = st.checkbox(f"🔽 Copier adresse siège : {main_addr}", key=f"chk_{key}")
                    if use_same:
                        st.session_state[key] = main_addr
                        val = st.text_input(lbl, key=key, disabled=True)
                        data[f['name']] = main_addr
                    else:
                        val = st.text_input(lbl, key=key, disabled=False)
                        data[f['name']] = val
                
                elif f['type'] == "SIRET":
                    val = st.text_input(lbl, key=key)
                    data[f['name']] = val
                        
                elif f['type'] == "Fichier/Image":
                    files_map[f['name']] = st.file_uploader(lbl, accept_multiple_files=True, key=key)
                    
                else: 
                    data[f['name']] = st.text_input(lbl, key=key)

            st.write("")
            st.divider()

            if st.button("💾 ENREGISTRER LE DOSSIER", type="primary", use_container_width=True):
                missing = []
                for f in fields:
                    if f.get('required') and f['type'] not in ["Section/Titre", "Fichier/Image"]:
                         k = f"f_{sel_col['id']}_{fields.index(f)}_{f['name']}_{FORM_ID}"
                         if not st.session_state.get(k):
                             missing.append(f['name'])
                
                if missing:
                    st.error(f"❌ Champs obligatoires manquants : {', '.join(missing)}")
                else:
                    with st.spinner("Enregistrement en cours..."):
                        for fname, flist in files_map.items():
                            urls = []
                            if flist:
                                for fi in flist:
                                    path = f"{MY_COMPANY_ID}/{sel_col['id']}/{int(time.time())}_{fi.name}"
                                    u = upload_file(fi, path)
                                    if u: urls.append(u)
                            data[fname] = urls
                        
                        supabase.table("records").insert({
                            "collection_id": sel_col['id'], "data": data, "created_by": st.session_state.user.id
                        }).execute()
                        
                        st.success("✅ Dossier créé avec succès !")
                        
                        for k in list(st.session_state.keys()):
                            if k.startswith(f"f_{sel_col['id']}"): del st.session_state[k]
                        
                        if "siret_search_bar" in st.session_state:
                            del st.session_state["siret_search_bar"]
                        
                        st.session_state.form_reset_id += 1
                        time.sleep(1)
                        st.rerun()

# ONGLET 2 : GESTION
with tabs[1]:
    st.header("📂 Gestion des Dossiers")
    my_acts = supabase.table("activities").select("id").eq("company_id", MY_COMPANY_ID).execute().data
    
    if my_acts:
        act_ids = [a['id'] for a in my_acts]
        my_cols = supabase.table("collections").select("*").in_("activity_id", act_ids).execute().data
        
        if my_cols:
            col_ids = [c['id'] for c in my_cols]
            recs = supabase.table("records").select("*, collections(name, fields)").in_("collection_id", col_ids).order('created_at', desc=True).execute().data
            
            if recs:
                st.write(f"**{len(recs)} dossiers trouvés**")
                
                search_map = {}
                for r in recs:
                    d = r['data']
                    client_name = next((v for k, v in d.items() if "nom" in k.lower() and "entreprise" not in k.lower() and "sociale" not in k.lower()), "Client Inconnu")
                    company_name = next((v for k, v in d.items() if any(x in k.lower() for x in ["raison sociale", "société", "entreprise"])), "")
                    
                    label_parts = [f"👤 {client_name}"]
                    if company_name: label_parts.append(f"🏢 {company_name}")
                    label_parts.append(f"📄 {r['collections']['name']}")
                    label_parts.append(f"📅 {r['created_at'][:10]}")
                    
                    full_label = "  |  ".join(label_parts)
                    search_map[full_label] = r

                sel_label = st.selectbox("Sélectionner le dossier à gérer :", list(search_map.keys()))
                
                if sel_label:
                    r = search_map[sel_label]
                    fields_def = r['collections']['fields']
                    current_data = r['data']
                    
                    st.divider()
                    
                    # ZONE 1 : MODIF
                    st.subheader("📝 Modifier les informations")
                    with st.form(f"edit_form_{r['id']}"):
                        updated_data = current_data.copy()
                        for f in fields_def:
                            f_name = f['name']
                            f_type = f['type']
                            if f_type == "Fichier/Image": continue
                            current_val = current_data.get(f_name, "")
                            if f_type == "Section/Titre": st.markdown(f"**{f_name}**")
                            else: updated_data[f_name] = st.text_input(f_name, value=current_val)
                        
                        if st.form_submit_button("💾 Sauvegarder les modifications"):
                            supabase.table("records").update({"data": updated_data}).eq("id", r['id']).execute()
                            st.success("Mis à jour !")
                            time.sleep(1)
                            st.rerun()

                    st.divider()
                    
                    # ZONE 2 : FICHIERS
                    st.subheader("📂 Gestion des Fichiers")
                    file_fields = [f for f in fields_def if f['type'] == "Fichier/Image"]
                    
                    # Compteur global de fichiers pour ce dossier
                    total_files_count = 0
                    all_files_urls = []
                    
                    if not file_fields:
                        st.info("Pas de champs fichiers.")
                    else:
                        for ff in file_fields:
                            fname = ff['name']
                            existing_urls = current_data.get(fname, [])
                            if not isinstance(existing_urls, list): existing_urls = []
                            
                            # On ajoute au compteur global
                            total_files_count += len(existing_urls)
                            all_files_urls.extend(existing_urls)
                            
                            with st.expander(f"📁 {fname} ({len(existing_urls)} fichiers)", expanded=True):
                                if existing_urls:
                                    for i, url in enumerate(existing_urls):
                                        c_view, c_del = st.columns([4, 1])
                                        display_name = url.split('/')[-1] if '/' in url else f"Fichier {i+1}"
                                        c_view.markdown(f"📄 [{display_name}]({url})")
                                        if c_del.button("❌", key=f"del_file_{r['id']}_{fname}_{i}"):
                                            new_url_list = [u for u in existing_urls if u != url]
                                            current_data[fname] = new_url_list
                                            supabase.table("records").update({"data": current_data}).eq("id", r['id']).execute()
                                            st.toast("Supprimé !")
                                            time.sleep(0.5)
                                            st.rerun()
                                else: st.caption("Vide.")
                                
                                st.write("---")
                                upload_key = f"up_{r['id']}_{fname}_{st.session_state.upload_reset_id}"
                                new_files = st.file_uploader(f"Ajout {fname}", accept_multiple_files=True, key=upload_key, label_visibility="collapsed")
                                
                                if new_files:
                                    if st.button(f"Envoyer", key=f"send_{r['id']}_{fname}"):
                                        with st.spinner("Envoi..."):
                                            added_urls = []
                                            for nf in new_files:
                                                path = f"{MY_COMPANY_ID}/{r['collection_id']}/{r['id']}_{int(time.time())}_{nf.name}"
                                                pub_url = upload_file(nf, path)
                                                if pub_url: added_urls.append(pub_url)
                                            final_list = existing_urls + added_urls
                                            current_data[fname] = final_list
                                            supabase.table("records").update({"data": current_data}).eq("id", r['id']).execute()
                                            st.success("Ajouté !")
                                            st.session_state.upload_reset_id += 1
                                            time.sleep(1)
                                            st.rerun()
                    
                    # --- ZONE 3 : GENERATEUR PDF COMPLET (V24) ---
                    if total_files_count >= 2:
                        st.divider()
                        st.subheader("🖨️ Fusionner les documents")
                        st.caption("Générez un PDF unique contenant tous les fichiers du dossier.")
                        
                        if st.button("📄 GÉNÉRER LE DOSSIER COMPLET (PDF)", use_container_width=True, type="primary"):
                            with st.spinner("Fusion des documents en cours..."):
                                pdf_data = merge_files_to_pdf(all_files_urls)
                                st.success("PDF généré !")
                                st.download_button(
                                    label="📥 Télécharger le Dossier Complet",
                                    data=pdf_data,
                                    file_name=f"Dossier_Complet_{r['id']}.pdf",
                                    mime="application/pdf",
                                    use_container_width=True
                                )

                    # ZONE 4 : SUPPRESSION DOSSIER
                    if MY_ROLE in ["admin", "super_admin"]:
                        st.divider()
                        st.markdown("### ⚠️ Zone de Danger")
                        with st.expander("Supprimer ce dossier définitivement"):
                            st.warning("Cette action est irréversible.")
                            if st.button("💀 Confirmer la suppression du dossier", type="primary"):
                                supabase.table("records").delete().eq("id", r['id']).execute()
                                st.success("Dossier supprimé.")
                                time.sleep(1)
                                st.rerun()

            else:
                st.info("Aucun dossier.")
        else:
            st.info("Pas de modèles.")
    else:
        st.info("Pas d'activités.")

# ONGLET 3 : CONFIG
if len(tabs) > 2:
    with tabs[2]:
        st.header("⚙️ Configuration Avancée")
        
        # 1. ACTIVITÉS
        st.subheader("1. Activités")
        c1, c2 = st.columns([1, 2])
        with c1:
            with st.form("new_act_v14"):
                n_act = st.text_input("Ajouter une activité", placeholder="Ex: Isolation")
                if st.form_submit_button("Ajouter"):
                    if n_act:
                        supabase.table("activities").insert({"name": n_act, "company_id": MY_COMPANY_ID}).execute()
                        st.success("Ajouté !")
                        st.rerun()
        with c2:
            st.write("**Existantes :**")
            current_acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
            if current_acts:
                for act in current_acts:
                    ca, cb = st.columns([4, 1])
                    ca.info(f"📌 {act['name']}")
                    if cb.button("🗑️", key=f"del_act_{act['id']}"):
                        supabase.table("activities").delete().eq("id", act['id']).execute()
                        st.rerun()
            else: st.caption("Vide.")

        st.divider()

        # 2. MODÈLES
        st.subheader("2. Modèles de Dossiers")
        if not current_acts:
            st.warning("Créez d'abord une activité.")
        else:
            act_names = [a['name'] for a in current_acts]
            selected_act_name = st.selectbox("Activité", act_names, key="config_act_selection")
            selected_act_id = next(a['id'] for a in current_acts if a['name'] == selected_act_name)
            
            # A. CRÉATION
            with st.expander("➕ Créer un nouveau modèle", expanded=False):
                st.markdown("#### Nouveau Modèle")
                new_model_name = st.text_input("Nom du modèle")
                if "temp_fields" not in st.session_state: st.session_state.temp_fields = []

                c_f1, c_f2, c_f3, c_f4 = st.columns([3, 2, 1, 1])
                f_name = c_f1.text_input("Nom champ")
                f_type = c_f2.selectbox("Type", ["Texte Court", "Texte Long", "Date", "SIRET", "Adresse", "Adresse Travaux", "Section/Titre", "Fichier/Image"])
                f_req = c_f3.checkbox("Obligatoire ?", value=False)
                
                if c_f4.button("Ajouter"):
                    if f_name:
                        st.session_state.temp_fields.append({"name": f_name, "type": f_type, "required": f_req})
                        st.rerun()

                if st.session_state.temp_fields:
                    st.write("---")
                    for idx, f in enumerate(st.session_state.temp_fields):
                        cols = st.columns([0.5, 4, 2, 1])
                        cols[0].write(f"{idx+1}")
                        cols[1].write(f"**{f['name']}**")
                        cols[2].caption(f"{f['type']}")
                        if cols[3].button("❌", key=f"rm_{idx}"):
                            st.session_state.temp_fields.pop(idx)
                            st.rerun()
                    
                    st.info("👇 Glissez-déposez pour trier :")
                    labels = [f"{f['name']}  ::  [{f['type']}]" for f in st.session_state.temp_fields]
                    sorted_labels = sort_items(labels, direction='vertical')
                    
                    if sorted_labels != labels:
                        new_order = []
                        for l in sorted_labels:
                            for f in st.session_state.temp_fields:
                                if f"{f['name']}  ::  [{f['type']}]" == l:
                                    new_order.append(f)
                                    break
                        st.session_state.temp_fields = new_order

                    if st.button("💾 SAUVEGARDER LE MODÈLE", type="primary"):
                        if new_model_name:
                            supabase.table("collections").insert({
                                "name": new_model_name, "activity_id": selected_act_id, "fields": st.session_state.temp_fields
                            }).execute()
                            st.success("Modèle créé !")
                            st.session_state.temp_fields = []
                            st.rerun()

            # B. MODIFICATION
            st.write("---")
            st.write(f"**Gérer les modèles existants :**")
            existing_models = supabase.table("collections").select("*").eq("activity_id", selected_act_id).execute().data
            
            if existing_models:
                for mod in existing_models:
                    with st.expander(f"📝 {mod['name']} (Modifier)", expanded=False):
                        tracker_key = f"update_counter_{mod['id']}"
                        if tracker_key not in st.session_state: st.session_state[tracker_key] = 0

                        st.markdown("##### ➕ Ajouter un champ")
                        c_a1, c_a2, c_a3, c_a4 = st.columns([3, 2, 1, 1])
                        n_fn = c_a1.text_input("Nom", key=f"n_fn_{mod['id']}")
                        n_ft = c_a2.selectbox("Type", ["Texte Court", "Texte Long", "Date", "SIRET", "Adresse", "Adresse Travaux", "Section/Titre", "Fichier/Image"], key=f"n_ft_{mod['id']}")
                        n_fr = c_a3.checkbox("Requis?", key=f"n_fr_{mod['id']}")
                        
                        if c_a4.button("Ajouter", key=f"add_btn_{mod['id']}"):
                            if n_fn:
                                new_field = {"name": n_fn, "type": n_ft, "required": n_fr}
                                updated_fields = mod['fields'] + [new_field]
                                supabase.table("collections").update({"fields": updated_fields}).eq("id", mod['id']).execute()
                                st.session_state[tracker_key] += 1
                                st.success("Champ ajouté !")
                                time.sleep(0.5)
                                st.rerun()

                        st.markdown("##### 🗑️ Supprimer des champs")
                        curr_fields = mod['fields']
                        field_names = [f['name'] for f in curr_fields]
                        to_delete = st.multiselect("Sélectionnez les champs à supprimer :", field_names, key=f"del_sel_{mod['id']}")
                        
                        if to_delete:
                            if st.button(f"Confirmer la suppression", key=f"conf_del_{mod['id']}"):
                                remaining_fields = [f for f in curr_fields if f['name'] not in to_delete]
                                supabase.table("collections").update({"fields": remaining_fields}).eq("id", mod['id']).execute()
                                st.session_state[tracker_key] += 1
                                st.success("Supprimé !")
                                time.sleep(0.5)
                                st.rerun()

                        st.markdown("##### 🔃 Réorganiser l'ordre")
                        current_f_labels = [f"{f['name']}  ::  [{f['type']}]" for f in curr_fields]
                        dynamic_sort_key = f"sort_{mod['id']}_{st.session_state[tracker_key]}"
                        sorted_f_labels = sort_items(current_f_labels, direction='vertical', key=dynamic_sort_key)
                        
                        col_valid, col_delete_mod = st.columns([3, 1])
                        if col_valid.button("💾 Valider le nouvel ordre", key=f"save_ord_{mod['id']}"):
                            final_list = []
                            for l in sorted_f_labels:
                                for f in curr_fields:
                                    if f"{f['name']}  ::  [{f['type']}]" == l:
                                        final_list.append(f)
                                        break
                            existing_names = [x['name'] for x in final_list]
                            for f in curr_fields:
                                if f['name'] not in existing_names: final_list.append(f)

                            supabase.table("collections").update({"fields": final_list}).eq("id", mod['id']).execute()
                            st.success("Sauvegardé !")
                            time.sleep(0.5)
                            st.rerun()
                            
                        if col_delete_mod.button("💀 Supprimer Modèle", key=f"kill_mod_{mod['id']}", type="primary"):
                            supabase.table("collections").delete().eq("id", mod['id']).execute()
                            st.rerun()
            else: st.caption("Aucun modèle ici.")

# ONGLET 4 : USERS
if len(tabs) > 3:
    with tabs[3]:
        st.header("👥 Utilisateurs")
        with st.form("add_user"):
            new_email = st.text_input("Email")
            new_pass = st.text_input("Mot de passe", type="password")
            new_role = st.selectbox("Rôle", ["user", "admin"])
            
            if st.form_submit_button("Ajouter"):
                try:
                    res = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                    if res.user:
                        supabase.table("profiles").insert({
                            "id": res.user.id, "email": new_email, "company_id": MY_COMPANY_ID,
                            "role": new_role, "full_name": new_email.split('@')[0]
                        }).execute()
                        st.success("Utilisateur créé !")
                    else: st.warning("Problème Auth.")
                except Exception as e: st.error(f"Erreur : {e}")
            
        st.divider()
        users = supabase.table("profiles").select("email, role, full_name").eq("company_id", MY_COMPANY_ID).execute().data
        if users: st.dataframe(users)
