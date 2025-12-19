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
        # MENU DÉROULANT ACTIVITÉ 1 (ID OK)
        act_choice = st.selectbox("Activité", [a['name'] for a in activities])
        act_id = next(a['id'] for a in activities if a['name'] == act_choice)
        
        collections = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        
        if collections:
            col_choice = st.selectbox("Modèle", [c['name'] for c in collections])
            sel_col = next(c for c in collections if c['name'] == col_choice)
            fields = sel_col['fields']
            
            # --- AUTO FILL SIRET ---
            if any(f['type'] == "SIRET" for f in fields):
                with st.expander("⚡ Remplissage SIRET", expanded=True):
                    c_s, c_b = st.columns([3, 1])
                    siret_in = c_s.text_input("SIRET", label_visibility="collapsed")
                    if c_b.button("Remplir"):
                        infos = get_siret_info(siret_in)
                        if infos:
                            for i, f in enumerate(fields):
                                key = f"f_{sel_col['id']}_{i}_{f['name']}"
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
                key = f"f_{sel_col['id']}_{i}_{f['name']}"
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
                    if use_same and main_addr:
                        if st.session_state[key] != main_addr:
                            st.session_state[key] = main_addr
                            st.rerun()
                    
                    val = st.text_input(lbl, key=key)
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
                         k = f"f_{sel_col['id']}_{fields.index(f)}_{f['name']}"
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
                        time.sleep(1)
                        st.rerun()

# ONGLET 2 : GESTION
with tabs[1]:
    st.header("📂 Dossiers")
    my_acts = supabase.table("activities").select("id").eq("company_id", MY_COMPANY_ID).execute().data
    if my_acts:
        act_ids = [a['id'] for a in my_acts]
        my_cols = supabase.table("collections").select("*").in_("activity_id", act_ids).execute().data
        
        if my_cols:
            col_ids = [c['id'] for c in my_cols]
            recs = supabase.table("records").select("*, collections(name, fields)").in_("collection_id", col_ids).execute().data
            
            if recs:
                st.write(f"Total : {len(recs)} dossiers")
                search_map = {f"#{r['id']} - {r['collections']['name']} ({r['created_at'][:10]})": r for r in recs}
                sel = st.selectbox("Rechercher", list(search_map.keys()))
                if sel:
                    r = search_map[sel]
                    st.markdown(f"### Dossier #{r['id']}")
                    st.json(r['data'], expanded=False)
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
        
        # --- 1. ACTIVITÉS ---
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
            else:
                st.caption("Vide.")

        st.divider()

        # --- 2. MODÈLES ---
        st.subheader("2. Modèles de Dossiers")
        
        if not current_acts:
            st.warning("Créez d'abord une activité.")
        else:
            act_names = [a['name'] for a in current_acts]
            # MENU DÉROULANT ACTIVITÉ 2 (CORRIGÉ AVEC KEY)
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
                        st.info("💡 Changez l'ordre des champs puis cliquez sur 'Valider'.")
                        
                        curr_fields = mod['fields']
                        f_labels = [f"{f['name']}  ::  [{f['type']}]" for f in curr_fields]
                        
                        # Tri
                        s_labels = sort_items(f_labels, direction='vertical', key=f"sort_{mod['id']}")
                        
                        col_s, col_d = st.columns([3, 1])
                        
                        if col_s.button("💾 Valider le nouvel ordre", key=f"save_{mod['id']}"):
                            new_list = []
                            for l in s_labels:
                                for f in curr_fields:
                                    if f"{f['name']}  ::  [{f['type']}]" == l:
                                        new_list.append(f)
                                        break
                            
                            supabase.table("collections").update({"fields": new_list}).eq("id", mod['id']).execute()
                            st.success("Ordre mis à jour !")
                            time.sleep(1)
                            st.rerun()
                            
                        if col_d.button("🗑️ Supprimer", key=f"del_{mod['id']}", type="primary"):
                            supabase.table("collections").delete().eq("id", mod['id']).execute()
                            st.rerun()
            else:
                st.caption("Aucun modèle ici.")

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
                    else:
                        st.warning("Problème Auth.")
                except Exception as e:
                    st.error(f"Erreur : {e}")
            
        st.divider()
        users = supabase.table("profiles").select("email, role, full_name").eq("company_id", MY_COMPANY_ID).execute().data
        if users:
            st.dataframe(users)
