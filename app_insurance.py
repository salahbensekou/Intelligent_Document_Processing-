# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Env (.env)
try:
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv(), override=True)
except Exception:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# Paths + sys.path (pour imports src/)
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"
UPLOADS = ROOT_DIR / "uploads"
RESULTS = ROOT_DIR / "results"

for d in (UPLOADS, RESULTS, TEMPLATES_DIR, STATIC_DIR):
    d.mkdir(exist_ok=True, parents=True)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers ENV: construire un DB_URL MySQL robuste (mot de passe avec @ etc.)
def _build_mysql_db_url_from_parts() -> Optional[str]:
    """
    Construit DB_URL depuis DB_USER/DB_PASSWORD/DB_HOST/DB_PORT/DB_NAME
    et encode le password (quote_plus) pour éviter le bug "2001@localhost".
    """
    driver = os.getenv("DB_DRIVER", "mysql+pymysql")
    user = os.getenv("DB_USER", "root")
    # certains .env mettent "password=" en minuscule -> on le prend aussi
    pwd = os.getenv("DB_PASSWORD") or os.getenv("password") or ""
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    name = os.getenv("DB_NAME", "insurance_db")

    if not user or not host or not name:
        return None

    pwd_enc = quote_plus(pwd)  # encode @ -> %40
    return f"{driver}://{user}:{pwd_enc}@{host}:{port}/{name}?charset=utf8mb4"


def _ensure_db_url():
    """
    Si DB_URL absent, le construit.
    Si DB_URL présent mais que tu utilises DB_PASSWORD avec caractères spéciaux,
    le remplace par une version safe.
    """
    db_url = os.getenv("DB_URL", "").strip()
    pwd = os.getenv("DB_PASSWORD") or os.getenv("password") or ""

    # Si DB_URL manquant => construire
    if not db_url:
        new_url = _build_mysql_db_url_from_parts()
        if new_url:
            os.environ["DB_URL"] = new_url
        return

    # Si l'utilisateur a mis DB_URL avec placeholder "password"
    # ou si on détecte que DB_PASSWORD contient des chars spéciaux,
    # on reconstruit un URL propre depuis les parts.
    if pwd and (("password@" in db_url) or ("@" in pwd) or (":" in pwd) or ("/" in pwd)):
        new_url = _build_mysql_db_url_from_parts()
        if new_url:
            os.environ["DB_URL"] = new_url


_ensure_db_url()

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline imports
from src.insurance_const import ALL_FIELDS, validate_field
from src.insurance_extractor import FieldExtractor
from src.anomaly_detector import AnomalyDetector

# LLM clients existants (Gemini/OpenAI)
from src.insurance_llm_client import GeminiInsuranceClient, InsuranceLLMClient

import src.insurance_db as insurance_db
from src.insurance_db import (
    init_db,
    save_insurance_document,
    save_anomalies,
    list_documents,
    get_document,
    get_document_dataframe,
    get_anomalies_dataframe,
    compare_documents_db,
    SessionLocal,
    InsuranceDocument,
)

# pour compter les anomalies sans accéder à doc.anomalies (évite erreurs relation)
try:
    from src.insurance_db import DocumentAnomaly
except Exception:
    DocumentAnomaly = None  # type: ignore

# ─────────────────────────────────────────────────────────────────────────────
# OCR setup (Tesseract)
def _configure_tesseract() -> Tuple[bool, Optional[str]]:
    """
    Configure pytesseract pour Windows si tesseract n'est pas dans PATH.
    Utilise env TESSERACT_CMD si fourni.
    """
    try:
        import pytesseract  # noqa
    except Exception:
        return False, "pytesseract non installé"

    tcmd = os.getenv("TESSERACT_CMD", "").strip()
    candidates = []
    if tcmd:
        candidates.append(tcmd)

    # chemins usuels Windows
    candidates += [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    # cas fréquent chez toi: AppData\Local\Programs\Tesseract-OCR\tesseract.exe
    user_home = os.path.expanduser("~")
    candidates.append(str(Path(user_home) / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe"))

    found = None
    for c in candidates:
        if c and Path(c).exists():
            found = c
            break

    if found:
        try:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = found
            return True, found
        except Exception as e:
            return False, f"Erreur config tesseract_cmd: {e}"

    # Pas trouvé => on laisse pytesseract tenter PATH
    return True, None


OCR_OK, OCR_TESS_PATH = _configure_tesseract()

# ─────────────────────────────────────────────────────────────────────────────
# Extraction texte: PDF (avec OCR si scanné), DOCX, images
def _extract_docx(filepath: str) -> List[str]:
    from docx import Document as DocxDocument

    doc = DocxDocument(filepath)
    text = "\n".join([p.text for p in doc.paragraphs])
    return [text]


def _ocr_image_pil(image) -> str:
    """
    OCR sur image PIL. Lang configurable via OCR_LANG.
    Fallback eng si fra non dispo.
    """
    if not OCR_OK:
        return ""

    try:
        import pytesseract

        lang = os.getenv("OCR_LANG", "fra+eng")
        try:
            return pytesseract.image_to_string(image, lang=lang)
        except Exception:
            # fallback
            return pytesseract.image_to_string(image, lang="eng")
    except Exception:
        return ""


def _extract_pdf_pages_text_with_ocr(filepath: str) -> List[str]:
    """
    1) Essaye d'extraire du texte (PyMuPDF).
    2) Si page quasi vide => OCR de la page rendue en image.
    """
    pages: List[str] = []
    try:
        import fitz  # PyMuPDF
        from PIL import Image
    except Exception:
        # fallback PyPDF2 (sans OCR)
        try:
            import PyPDF2

            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                return [(p.extract_text() or "") for p in reader.pages]
        except Exception:
            return [""]

    doc = fitz.open(filepath)
    ocr_threshold = int(os.getenv("OCR_TEXT_MIN_CHARS", "40"))

    for page in doc:
        txt = page.get_text("text") or ""
        if len(txt.strip()) >= ocr_threshold:
            pages.append(txt)
            continue

        # OCR si texte insuffisant
        if not OCR_OK:
            pages.append(txt)  # au moins ce qu'on a
            continue

        try:
            dpi = int(os.getenv("OCR_DPI", "250"))
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            ocr_txt = _ocr_image_pil(img)
            merged = (txt + "\n" + ocr_txt).strip()
            pages.append(merged)
        except Exception:
            pages.append(txt)

    doc.close()
    return pages


def _extract_image_text(filepath: str) -> List[str]:
    try:
        from PIL import Image
    except Exception:
        return [""]

    try:
        img = Image.open(filepath)
        return [_ocr_image_pil(img)]
    except Exception:
        return [""]


# ─────────────────────────────────────────────────────────────────────────────
# LLM OpenRouter (optionnel, sans modifier src/)
class OpenRouterInsuranceClient:
    """
    Utilise OpenRouter API (https://openrouter.ai/api/v1/chat/completions)
    Env:
      OPENROUTER_API_KEY (obligatoire)
      OPENROUTER_MODEL (ex: "openai/gpt-4o-mini" ou autre)
      OPENROUTER_SITE_URL (optionnel)
      OPENROUTER_APP_NAME (optionnel)
    """
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY manquant")
        self.model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
        self.site = os.getenv("OPENROUTER_SITE_URL", "").strip()
        self.app = os.getenv("OPENROUTER_APP_NAME", "Insurance Extractor").strip()

    def extract_fields(self, text: str) -> Dict[str, Any]:
        import requests

        system = (
            "Tu es un assistant d'extraction d'informations. "
            "Tu dois EXTRAIRE uniquement ce qui est présent dans le texte. "
            "Si une info est absente, mets value=null et found=false. "
            "Réponds STRICTEMENT en JSON."
        )

        schema_hint = {
            "fields": {
                k: {"value": None, "confidence": 0.0, "found": False, "evidence": ""}
                for k in ALL_FIELDS
            }
        }

        user = (
            "Extrait les champs suivants depuis le texte.\n"
            f"Champs: {ALL_FIELDS}\n\n"
            "Contraintes:\n"
            "- Pas d'invention.\n"
            "- evidence: courte citation exacte du texte (ou vide).\n"
            "- confidence: 0..1.\n"
            "JSON attendu:\n"
            f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
            "TEXTE:\n"
            f"{text[:12000]}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site:
            headers["HTTP-Referer"] = self.site
        if self.app:
            headers["X-Title"] = self.app

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

        # extraire JSON du message
        try:
            # Si le modèle renvoie ```json ... ```
            m = re.search(r"\{.*\}", content, flags=re.S)
            if m:
                return json.loads(m.group(0))
            return json.loads(content)
        except Exception:
            return {"fields": {}}


# ─────────────────────────────────────────────────────────────────────────────
# Flask App
app = Flask(__name__, template_folder=str(TEMPLATES_DIR), static_folder=str(STATIC_DIR))
app.secret_key = os.getenv("FLASK_SECRET_KEY", "insurance-secret-key-2026")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "jpg", "jpeg", "png"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _normalize_field_dict(obj: Any) -> Dict[str, Any]:
    """Assure le format {"value":..., "confidence":..., "found":..., "evidence":...}."""
    if isinstance(obj, dict):
        value = obj.get("value")
        conf = float(obj.get("confidence", 0.0) or 0.0)
        found = obj.get("found")
        evidence = obj.get("evidence", "") or ""
        if found is None:
            found = value not in (None, "")
        return {"value": value, "confidence": conf, "found": bool(found), "evidence": evidence}
    value = obj
    return {"value": value, "confidence": 0.5 if value else 0.0, "found": bool(value), "evidence": ""}


def _value_is_supported_by_text(value: Any, full_text: str) -> bool:
    """
    Anti-hallucination simple:
    - si value est string/num => doit apparaître (approx) dans le texte
    """
    if value is None:
        return True
    s = str(value).strip()
    if not s:
        return True

    # normalisation légère
    text = full_text.lower()
    s2 = s.lower()

    # pour numéros: enlever espaces/-
    def compact(x: str) -> str:
        return re.sub(r"[\s\-_/.:]", "", x)

    if any(ch.isdigit() for ch in s2):
        return compact(s2) in compact(text)

    return s2 in text


def _pick_llm_client() -> Optional[Any]:
    """
    LLM_PROVIDER:
      - auto (default): Gemini -> OpenRouter -> OpenAI
      - gemini / openrouter / openai
    """
    if os.getenv("USE_LLM", "false").lower() != "true":
        return None

    provider = os.getenv("LLM_PROVIDER", "auto").lower().strip()

    def has(k: str) -> bool:
        return bool(os.getenv(k, "").strip())

    order = []
    if provider == "gemini":
        order = ["gemini"]
    elif provider == "openrouter":
        order = ["openrouter"]
    elif provider == "openai":
        order = ["openai"]
    else:
        order = ["gemini", "openrouter", "openai"]

    for p in order:
        try:
            if p == "gemini" and has("GEMINI_API_KEY"):
                return GeminiInsuranceClient()
            if p == "openrouter" and has("OPENROUTER_API_KEY"):
                return OpenRouterInsuranceClient()
            if p == "openai" and has("OPENAI_API_KEY"):
                return InsuranceLLMClient()
        except Exception:
            continue

    return None


def extract_from_file(file_path: Path) -> Tuple[Dict[str, Any], List[str]]:
    """
    Extrait les données d'assurance d'un fichier.
    Retourne: (result, warnings)
    """
    warnings: List[str] = []
    suffix = file_path.suffix.lower()

    # 1) Extraction texte
    if suffix == ".pdf":
        pages_text = _extract_pdf_pages_text_with_ocr(str(file_path))
        if OCR_OK and sum(len(p.strip()) for p in pages_text) < 60:
            warnings.append("PDF semble scanné ou vide: OCR n'a pas trouvé beaucoup de texte.")
    elif suffix in [".docx", ".doc"]:
        pages_text = _extract_docx(str(file_path))
    elif suffix in [".jpg", ".jpeg", ".png"]:
        pages_text = _extract_image_text(str(file_path))
        if OCR_OK and len((pages_text[0] if pages_text else "").strip()) < 10:
            warnings.append("OCR image: peu de texte détecté.")
    else:
        raise ValueError("Format de fichier non supporté")

    full_text = "\n\n".join(pages_text).strip()

    # 2) Regex extraction
    extractor = FieldExtractor()
    regex_result = extractor.extract_all_fields(full_text)

    # Normaliser
    for k in list(regex_result.keys()):
        regex_result[k] = _normalize_field_dict(regex_result[k])

    # garantir clés ALL_FIELDS
    for f in ALL_FIELDS:
        if f not in regex_result:
            regex_result[f] = _normalize_field_dict({})

    # 3) LLM extraction (optionnel) -> complète les champs manquants
    llm_client = _pick_llm_client()
    if llm_client:
        strict = os.getenv("LLM_STRICT", "true").lower() == "true"
        try:
            llm_result = llm_client.extract_fields(full_text) or {}
            llm_fields = (llm_result.get("fields") or {}) if isinstance(llm_result, dict) else {}

            for field_name in ALL_FIELDS:
                llm_field = _normalize_field_dict(llm_fields.get(field_name, {}))
                regex_field = _normalize_field_dict(regex_result.get(field_name, {}))

                # si LLM n'a rien trouvé, skip
                if not llm_field.get("found"):
                    continue

                # (anti-hallucination) si strict: valeur doit être supportée par texte
                if strict and not _value_is_supported_by_text(llm_field.get("value"), full_text):
                    continue

                # garder la meilleure confiance
                if (llm_field.get("confidence", 0.0) > regex_field.get("confidence", 0.0)) or (not regex_field.get("found")):
                    regex_result[field_name] = llm_field

        except Exception as e:
            warnings.append(f"Erreur LLM: {e}")

    # 4) Complétude
    found_count = sum(1 for f in regex_result.values() if isinstance(f, dict) and f.get("found"))
    completeness = found_count / len(ALL_FIELDS) if ALL_FIELDS else 0.0

    # 5) Type document (amélioré)
    doc_type = "unknown"
    text_lower = full_text.lower()

    if any(k in text_lower for k in ["police d'assurance", "contrat d'assurance", "conditions générales", "prime annuelle"]):
        doc_type = "police_assurance"
    elif any(k in text_lower for k in ["attestation", "certificat d'assurance"]):
        doc_type = "attestation_assurance"
    elif any(k in text_lower for k in ["demande", "souscription", "proposition d'assurance"]):
        doc_type = "demande_souscription"
    elif any(k in text_lower for k in ["carte nationale", "cin", "c.n.i", "carte d'identité", "numéro de carte"]):
        doc_type = "piece_identite"

    return (
        {
            "fields": regex_result,
            "completeness": completeness,
            "document_type": doc_type,
            "raw_text": full_text[:800],
        },
        warnings,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes
@app.route("/")
def index():
    return redirect(url_for("upload"))


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        files = request.files.getlist("files")

        if not files or all(f.filename == "" for f in files):
            flash("Aucun fichier sélectionné.", "error")
            return render_template("upload.html")

        results = []
        doc_ids: List[int] = []

        for file in files:
            if file.filename == "" or not allowed_file(file.filename):
                continue

            # éviter collision de noms
            original = secure_filename(file.filename)
            unique = f"{Path(original).stem}_{uuid.uuid4().hex[:8]}{Path(original).suffix}"
            filepath = UPLOADS / unique
            file.save(str(filepath))

            try:
                extraction_result, warns = extract_from_file(filepath)

                # flash warnings OCR/LLM si besoin
                for w in warns:
                    flash(f"{unique}: {w}", "warning")

                doc_id = save_insurance_document(unique, extraction_result, mode="replace")
                doc_ids.append(int(doc_id))

                results.append(
                    {
                        "filename": unique,
                        "doc_id": doc_id,
                        "completeness": f"{extraction_result['completeness']:.0%}",
                        "document_type": extraction_result["document_type"],
                        "status": "success",
                    }
                )
            except Exception as e:
                flash(f"Erreur pour {unique}: {str(e)}", "error")
                results.append({"filename": unique, "status": "error", "error": str(e)})

        # Détection d'anomalies si >=2 docs uploadés
        if len(doc_ids) >= 2:
            try:
                detector = AnomalyDetector()

                docs_data = []
                with SessionLocal() as session:
                    for did in doc_ids:
                        doc = session.get(InsuranceDocument, did)
                        if doc and getattr(doc, "json_data", None):
                            docs_data.append(json.loads(doc.json_data))

                if len(docs_data) >= 2:
                    comparison = detector.compare_multiple_documents(docs_data)

                    for comp in comparison.get("comparisons", []):
                        d1 = comp.get("doc1_index")
                        d2 = comp.get("doc2_index")
                        if d1 is None or d2 is None:
                            continue
                        if d1 < len(doc_ids) and d2 < len(doc_ids):
                            save_anomalies(
                                doc_ids[d1],
                                comp.get("anomalies", []),
                                compared_with_id=doc_ids[d2],
                            )

                    rec = comparison.get("recommendation", "")
                    if rec:
                        flash(rec, "info")
            except Exception as e:
                flash(f"Erreur détection anomalies: {str(e)}", "warning")

        return render_template("upload.html", results=results)

    return render_template("upload.html")


@app.route("/document/<int:doc_id>")
def view_document(doc_id: int):
    doc = get_document(doc_id)
    if not doc:
        flash("Document introuvable", "error")
        return redirect(url_for("documents"))

    df_fields = get_document_dataframe(doc_id)
    df_anomalies = get_anomalies_dataframe(doc_id)

    return render_template(
        "document_detail.html",
        document=doc,
        fields_table=df_fields.to_html(classes="table table-sm", index=False, escape=False),
        anomalies_table=df_anomalies.to_html(classes="table table-sm", index=False, escape=False)
        if not df_anomalies.empty
        else None,
        has_anomalies=not df_anomalies.empty,
    )


@app.route("/documents")
def documents():
    docs = list_documents()
    docs_list = []

    # has_anomalies sans toucher doc.anomalies
    with SessionLocal() as session:
        for doc in docs:
            has_anom = False
            if DocumentAnomaly is not None:
                has_anom = (
                    session.query(DocumentAnomaly.id)
                    .filter(DocumentAnomaly.document_id == doc.id)
                    .first()
                    is not None
                )

            docs_list.append(
                {
                    "id": doc.id,
                    "filename": doc.filename,
                    "type": doc.document_type,
                    "completeness": f"{doc.completeness:.0%}" if doc.completeness is not None else "N/A",
                    "uploaded_at": doc.uploaded_at.strftime("%d/%m/%Y %H:%M"),
                    "has_anomalies": has_anom,
                }
            )

    return render_template("documents_list.html", documents=docs_list)


@app.route("/compare", methods=["GET", "POST"])
def compare():
    if request.method == "POST":
        doc_ids = request.form.getlist("doc_ids")
        doc_ids = [int(did) for did in doc_ids if str(did).isdigit()]

        if len(doc_ids) < 2:
            flash("Sélectionnez au moins 2 documents à comparer.", "error")
            return redirect(url_for("compare"))

        try:
            result = compare_documents_db(doc_ids)
            if "error" in result:
                flash(result["error"], "error")
                return redirect(url_for("compare"))

            detector = AnomalyDetector()
            comparison = detector.compare_multiple_documents(result["data"])

            return render_template(
                "comparison_result.html",
                documents=result["documents"],
                comparison=comparison,
            )
        except Exception as e:
            flash(f"Erreur de comparaison: {str(e)}", "error")
            return redirect(url_for("compare"))

    docs = list_documents()
    return render_template("compare_select.html", documents=docs)


@app.route("/export/<int:doc_id>")
def export_document(doc_id: int):
    doc = get_document(doc_id)
    if not doc:
        flash("Document introuvable", "error")
        return redirect(url_for("documents"))

    df = get_document_dataframe(doc_id)

    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Extraction", index=False)
        df_anom = get_anomalies_dataframe(doc_id)
        if not df_anom.empty:
            df_anom.to_excel(writer, sheet_name="Anomalies", index=False)

    bio.seek(0)
    return send_file(
        bio,
        as_attachment=True,
        download_name=f"{Path(doc.filename).stem}_extraction.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/validate", methods=["POST"])
def api_validate():
    data = request.get_json(force=True)
    field_name = data.get("field")
    value = data.get("value")
    is_valid = validate_field(field_name, value)
    return jsonify({"valid": is_valid, "field": field_name, "value": value})


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Infos utiles au démarrage
    if OCR_TESS_PATH:
        print(f"[OCR] Tesseract détecté: {OCR_TESS_PATH}")
    else:
        if OCR_OK:
            print("[OCR] Tesseract non détecté par chemin fixe (PATH requis ou TESSERACT_CMD).")
        else:
            print("[OCR] pytesseract non disponible.")

    # Init DB (MySQL/SQLite selon DB_URL)
    init_db()

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
