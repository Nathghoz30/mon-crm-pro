# 🗂️ Universal CRM - Gestion de Dossiers Métier

Application de CRM et de Gestion Électronique de Documents (GED) ultra-flexible, conçue pour gérer des dossiers clients, des chantiers ou des projets administratifs.

**Technologies :** Python (Streamlit) & Supabase (PostgreSQL + Storage).

---

## ✨ Fonctionnalités Clés

### 🏗️ 1. Architecture Flexible (No-Code)
* **Structure dynamique :** Créez vos propres modèles de dossiers via l'interface Admin.
* **Organisation par Sections :** Découpez vos formulaires en blocs visuels (ex: "1. Contact", "2. Technique", "3. Documents").
* **Typage avancé :** Champs Texte, Nombre, Date, Email, Téléphone, Oui/Non, SIRET, Adresse, Adresse Travaux.

### ⚡ 2. Saisie Intelligente & Automatisée
* **API SIRET (Gouv.fr) :** Remplissage automatique des infos société (Nom, Adresse complète, Ville, CP) via le numéro SIRET.
* **Adresse Intelligente :** Case à cocher "Identique" pour copier instantanément l'adresse du siège vers l'adresse de travaux.
* **Interface Réactive :** Formulaire fluide avec mise à jour en temps réel.

### 📂 3. Gestion Documentaire (GED) & PDF
* **Upload Multi-fichiers :** Glisser-déposer plusieurs documents d'un coup.
* **Visualisation :** Liste claire des fichiers par dossier avec liens de téléchargement.
* **Fusion PDF 🖨️ :** Bouton pour fusionner **tous** les documents d'un dossier (Images JPG/PNG + PDFs) en un seul fichier PDF complet.

### 🛠️ 4. Administration Totale
* **Éditeur de Structure :** Réorganisez l'ordre des champs par simple Drag & Drop.
* **Modification à la volée :** Renommez des champs ou changez leur section sans toucher au code.

---

## 🚀 Installation Locale

### Pré-requis
* Python 3.9+
* Un compte [Supabase](https://supabase.com/) (Gratuit)

### 1. Cloner le projet
```bash
git clone [https://github.com/votre-pseudo/mon-crm-pro.git](https://github.com/votre-pseudo/mon-crm-pro.git)
cd mon-crm-pro
