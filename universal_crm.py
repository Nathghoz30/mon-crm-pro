import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime
import io
import time
import re  # <--- AJOUTÉ : Indispensable pour la sécurité email
from supabase import create_client, Client
from pypdf import PdfWriter, PdfReader
from PIL import Image

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("Librairie manquante. Installez-la via : pip install streamlit-sortables")
    st.stop()

# --- CONFIGURATION ---
st.set_page_config(page_title="Universal CRM SaaS", page_icon="🚀", layout="wide")

# --- INITIALISATION SUPABASE ---
@st.cache_resource
def init_connection():
    try:
        # Tente de charger depuis st.secrets, sinon valeurs par défaut pour éviter le crash immédiat
        url = st.secrets["SUPABASE_URL"] if "SUPABASE_URL" in st.secrets else "URL_MANQUANTE"
        key = st.secrets["SUPABASE_KEY"] if "SUPABASE_KEY" in st.secrets else "KEY_MANQUANTE"
        if url == "URL_MANQUANTE":
            st.error("⚠️ Secrets Supabase manquants dans .streamlit/secrets.toml")
            st.stop()
        return create_client(url, key)
    except Exception as e:
        st.error(f"Erreur de connexion Supabase : {e}")
        st.stop()

supabase = init_connection()

# --- GESTION ÉTAT SESSION ---
if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile' not in st.session_state:
    st.session_state.profile = None

# --- FONCTIONS UTILITAIRES ---

def login(email, password):
    try:
        # 1. Auth Supabase
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user = res.user
        
        # 2. Récupération du Profil Métier (Rôle, Entreprise)
        profile_data = supabase.table("profiles").select("*").eq("id", user.id).execute().data
        
        if profile_data:
            st.session_state.user = user
            st.session_state.profile = profile_data[0]
            st.success("Connexion réussie !")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("Utilisateur authentifié mais aucun profil trouvé. Contactez le support.")
    except Exception as e:
        st.error(f"Erreur de connexion : {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
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

# Infos de l'utilisateur connecté
MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

# Header & Logout
with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name', 'Utilisateur')}")
    st.caption(f"Rôle : {MY_ROLE}")
    if st.button("Déconnexion", use_container_width=True):
        logout()

st.title("Universal CRM SaaS 🚀")

# ------------------------------------------------------------------
# 👑 SUPER ADMIN DASHBOARD (Gestion des Entreprises)
# ------------------------------------------------------------------
if MY_ROLE == "super_admin":
    st.success("👑 Mode Super Admin activé")
    
    sa_tab1, sa_tab2 = st.tabs(["🏢 Gestion Entreprises", "👀 Accéder au CRM"])
    
    # --- CRÉATION SÉCURISÉE (CODE CORRIGÉ) ---
    with sa_tab1:
        st.subheader("Créer une nouvelle entreprise")
        with st.form("create_company"):
            c_name = st.text_input("Nom de l'entreprise")
            admin_email = st.text_input("Email de l'Admin principal")
            admin_pass = st.text_input("Mot de passe temporaire (min 6 car.)", type="password")
            
            submitted = st.form_submit_button("Créer Entreprise & Admin")
            
            if submitted:
                # 1. Validations préalables
                if not c_name or not admin_email or not admin_pass:
                    st.error("❌ Tous les champs sont requis.")
                    st.stop()
                
                if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", admin_email):
                    st.error("❌ Format d'email invalide.")
                    st.stop()
                
                if len(admin_pass) < 6:
                    st.warning("⚠️ Mot de passe trop court.")
                    st.stop()

                # 2. Processus de création avec Rollback
                new_comp_id = None
                try:
                    # A. Créer Entreprise
                    res_comp = supabase.table("companies").insert({"name": c_name}).execute()
                    if res_comp.data:
                        new_comp_id = res_comp.data[0]['id']
                    else:
                        raise Exception("Échec création entreprise (DB)")
                    
                    # B. Créer User Auth
                    res_auth = supabase.auth.sign_up({
                        "email": admin_email, 
                        "password": admin_pass,
                        "options": {
                            "data": {
                                "full_name": f"Admin {c_name}",
                                "company_id": new_comp_id,
                                "role": "admin"
                            }
                        }
                    })
                    
                    # Vérification échec silencieux Auth
                    if res_auth.user is None and res_auth.session is None:
                        raise Exception("L'utilisateur n'a pas pu être créé (Email déjà pris ?).")

                    # C. Succès
                    st.success(f"✅ Entreprise '{c_name}' et Admin '{admin_email}' créés avec succès !")
                    st.balloons()
                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Erreur : {e}")
                    # ROLLBACK : Nettoyage automatique
                    if new_comp_id:
                        st.warning("🔄 Annulation : Suppression de l'entreprise fantôme...")
                        supabase.table("companies").delete().eq("id", new_comp_id).execute()
                        st.info("✅ Base de données nettoyée.")

    with sa_tab2:
        st.write("Sélectionnez une entreprise pour voir son CRM :")
        all_comps = supabase.table("companies").select("*").execute().data
        comp_map = {c['name']: c['id'] for c in all_comps}
        target_comp_name = st.selectbox("Choisir Entreprise", list(comp_map.keys()))
        
        # SUPER ADMIN IMPERSONATION
        if target_comp_name:
            MY_COMPANY_ID = comp_map[target_comp_name]
            st.info(f"👀 Vous visualisez les données de : **{target_comp_name}**")
            st.divider()

# Si Super Admin n'a pas choisi d'entreprise, on arrête là
if MY_ROLE == "super_admin" and not MY_COMPANY_ID:
    st.warning("👈 Veuillez sélectionner une entreprise dans l'onglet 'Accéder au CRM' pour continuer.")
    st.stop()


# ------------------------------------------------------------------
# 🏢 CRM LOGIC (Filtré par MY_COMPANY_ID)
# ------------------------------------------------------------------

# Définition des onglets
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin", "super_admin"]:
    tabs_list.append("3. ⚙️ Configuration (Admin)")
    tabs_list.append("4. 👥 Utilisateurs")

tabs = st.tabs(tabs_list)

# ==========================================
# ONGLET 1 : NOUVEAU DOSSIER
# ==========================================
with tabs[0]:
    st.header("Créer un nouveau dossier")
    
    # Filtre par Company ID
    activities = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    
    if not activities:
        st.info("⚠️ Aucune activité configurée pour cette entreprise.")
        if MY_ROLE in ["admin", "super_admin"]:
            st.write("👉 Allez dans l'onglet **Configuration** pour commencer.")
    else:
        act_choice = st.selectbox("Activité", [a['name'] for a in activities])
        act_id = next(a['id'] for a in activities if a['name'] == act_choice)
        
        collections = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        
        if collections:
            col_choice = st.selectbox("Modèle", [c['name'] for c in collections])
            sel_col = next(c for c in collections if c['name'] == col_choice)
            fields = sel_col['fields']
            
            # --- AUTO-FILL SIRET ---
            if any(f['type'] == "SIRET" for f in fields):
                with st.expander("⚡ Remplissage Rapide via SIRET", expanded=True):
                    c_s, c_b = st.columns([3, 1])
                    siret_in = c_s.text_input("SIRET", label_visibility="collapsed")
                    if c_b.button("Remplir"):
                        infos = get_siret_info(siret_in)
                        if infos:
                            for i, f in enumerate(fields):
                                key = f"f_{sel_col['id']}_{i}_{f['name']}"
                                n = f['name'].lower()
                                val = None
                                if any(x in n for x in ["nom", "société"]): val = infos['NOM']
                                elif "adresse" in n: val = infos['ADRESSE']
                                elif "ville" in n: val = infos['VILLE']
                                elif "cp" in n: val = infos['CP']
                                if val: st.session_state[key] = val
                            st.success("Données chargées !")

            # --- FORMULAIRE ---
            with st.form("add_rec"):
                data = {}
                files_map = {}
                main_addr = ""
                
                for i, f in enumerate(fields):
                    key = f"f_{sel_col['id']}_{i}_{f['name']}"
                    lbl = f"{f['name']} *" if f.get('required') else f['name']
                    
                    if key not in st.session_state: st.session_state[key] = ""
                    
                    if f['type'] == "Section/Titre":
                        st.markdown(f"**{f['name']}**")
                    elif f['type'] == "Texte Court":
                        val = st.text_input(lbl, key=key)
                        data[f['name']] = val
                        if "adresse" in f['name'].lower() and "travaux" not in f['name'].lower(): main_addr = val
                    elif f['type'] == "Adresse Travaux":
                        st.text_input(lbl, key=key) # Le reste géré par logique visuelle
                        if st.checkbox(f"Identique siège ({main_addr}) ?", key=f"chk_{key}"):
                            data[f['name']] = main_addr
                        else:
                            data[f['name']] = st.session_state[key]
                    elif f['type'] == "Fichier/Image":
                        files_map[f['name']] = st.file_uploader(lbl, accept_multiple_files=True, key=key)
                    else:
                        data[f['name']] = st.text_input(lbl, key=key)

                if st.form_submit_button("Enregistrer"):
                    # Upload
                    for fname, flist in files_map.items():
                        urls = []
                        if flist:
                            for fi in flist:
                                path = f"{MY_COMPANY_ID}/{sel_col['id']}/{int(time.time())}_{fi.name}"
                                u = upload_file(fi, path)
                                if u: urls.append(u)
                        data[fname] = urls
                    
                    supabase.table("records").insert({
                        "collection_id": sel_col['id'],
                        "data": data,
                        "created_by": st.session_state.user.id
                    }).execute()
                    st.success("Dossier créé !")
                    # Clean state
                    for k in list(st.session_state.keys()):
                        if k.startswith(f"f_{sel_col['id']}"): del st.session_state[k]
                    time.sleep(1)
                    st.rerun()

# ==========================================
# ONGLET 2 : GESTION (Filtré)
# ==========================================
with tabs[1]:
    st.header("📂 Dossiers")
    
    # On récupère d'abord les modèles de CETTE entreprise via les activités
    my_acts = supabase.table("activities").select("id").eq("company_id", MY_COMPANY_ID).execute().data
    if my_acts:
        act_ids = [a['id'] for a in my_acts]
        # Supabase 'in_' attend un tuple ou liste
        my_cols = supabase.table("collections").select("*").in_("activity_id", act_ids).execute().data
        
        if my_cols:
            col_ids = [c['id'] for c in my_cols]
            # Fetch records
            recs = supabase.table("records").select("*, collections(name, fields)").in_("collection_id", col_ids).execute().data
            
            if recs:
                st.write(f"Nombre de dossiers trouvés : {len(recs)}")
                search_map = {f"#{r['id']} - {r['collections']['name']} (Créé le {r['created_at'][:10]})": r for r in recs}
                sel = st.selectbox("Rechercher un dossier", list(search_map.keys()))
                if sel:
                    r = search_map[sel]
                    st.markdown(f"### Dossier #{r['id']}")
                    st.json(r['data'], expanded=False)
                    
            else:
                st.info("Aucun dossier enregistré pour le moment.")
        else:
            st.info("Pas de modèles configurés.")
    else:
        st.info("Pas d'activités configurées.")

# ==========================================
# ONGLET 3 : CONFIG (ADMIN ONLY)
# ==========================================
if len(tabs) > 2:
    with tabs[2]:
        st.header("⚙️ Configuration Entreprise")
        
        c_act1, c_act2 = st.columns([1, 2])
        with c_act1:
            with st.form("new_act"):
                n_act = st.text_input("Nouvelle Activité")
                if st.form_submit_button("Ajouter"):
                    supabase.table("activities").insert({"name": n_act, "company_id": MY_COMPANY_ID}).execute()
                    st.success("Activité ajoutée !")
                    st.rerun()
        
        st.divider()
        st.subheader("Créer un Modèle de Dossier")
        
        # Récupérer les activités DE CETTE ENTREPRISE
        my_acts_config = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        
        if my_acts_config:
            act_sel = st.selectbox("Lier à l'activité", [a['name'] for a in my_acts_config])
            act_id_sel = next(a['id'] for a in my_acts_config if a['name'] == act_sel)
            
            col_name = st.text_input("Nom du modèle (ex: Audit RGE)")
            
            if "temp_fields" not in st.session_state: st.session_state.temp_fields = []
            
            c_f1, c_f2, c_f3 = st.columns([2, 1, 1])
            f_name = c_f1.text_input("Nom du champ")
            f_type = c_f2.selectbox("Type", ["Texte Court", "Texte Long", "Date", "SIRET", "Adresse Travaux", "Section/Titre", "Fichier/Image"])
            f_req = c_f3.checkbox("Obligatoire ?")
            
            if st.button("Ajouter ce champ"):
                st.session_state.temp_fields.append({"name": f_name, "type": f_type, "required": f_req})
            
            # Affichage dynamique des champs
            if st.session_state.temp_fields:
                st.write("Aperçu des champs :")
                st.dataframe(pd.DataFrame(st.session_state.temp_fields))
            
            if st.button("💾 Sauvegarder le Modèle"):
                supabase.table("collections").insert({
                    "name": col_name,
                    "activity_id": act_id_sel,
                    "fields": st.session_state.temp_fields
                }).execute()
                st.success("Modèle sauvegardé !")
                st.session_state.temp_fields = []
                st.rerun()
        else:
            st.warning("Créez d'abord une activité ci-dessus.")

# ==========================================
# ONGLET 4 : UTILISATEURS (ADMIN ONLY)
# ==========================================
if len(tabs) > 3:
    with tabs[3]:
        st.header("👥 Gestion des Utilisateurs")
        st.info("Ajoutez des collaborateurs à VOTRE entreprise.")
        
        with st.form("add_user"):
            new_email = st.text_input("Email collaborateur")
            new_pass = st.text_input("Mot de passe provisoire", type="password")
            new_role = st.selectbox("Rôle", ["user", "admin"])
            
            if st.form_submit_button("Créer Utilisateur"):
                try:
                    # Création Auth (C'est là que le trigger auto peut aider, mais on fait manuel ici)
                    res = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                    if res.user:
                        # Création Profil lié à MON entreprise (MY_COMPANY_ID)
                        supabase.table("profiles").insert({
                            "id": res.user.id,
                            "email": new_email,
                            "company_id": MY_COMPANY_ID,
                            "role": new_role,
                            "full_name": new_email.split('@')[0]
                        }).execute()
                        st.success("Utilisateur ajouté à votre équipe !")
                    else:
                        st.warning("Vérifiez si l'utilisateur existe déjà.")
                except Exception as e:
                    st.error(f"Erreur : {e}")
            
        st.divider()
        st.write("### Membres de l'équipe")
        users = supabase.table("profiles").select("email, role, full_name, last_sign_in_at").eq("company_id", MY_COMPANY_ID).execute().data
        if users:
            st.dataframe(users)
