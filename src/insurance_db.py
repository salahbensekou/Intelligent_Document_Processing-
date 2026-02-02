# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import os, datetime as dt, json
from typing import Dict, Any, List, Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, 
    ForeignKey, Text, Float, Boolean, UniqueConstraint
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Configuration DB
DB_URL = os.getenv("DB_URL")

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

if not DB_URL:
    DB_URL = f"sqlite:///{(DATA_DIR / 'insurance.db').as_posix()}"

engine = create_engine(DB_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

# ─────────────────────────────────────────────────────────────────────────────
# Modèles

class InsuranceDocument(Base):
    """Document d'assurance uploadé."""
    __tablename__ = "insurance_documents"
    
    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    document_type = Column(String(50))  # police, attestation, etc.
    completeness = Column(Float)  # % de champs extraits
    json_data = Column(Text)  # données complètes en JSON
    
    fields = relationship("ExtractedField", back_populates="document", cascade="all, delete-orphan")
    anomalies = relationship(
    "DocumentAnomaly",
    back_populates="document",
    cascade="all, delete-orphan",
    foreign_keys="DocumentAnomaly.document_id",  # << IMPORTANT
)


class ExtractedField(Base):
    """Champ extrait d'un document."""
    __tablename__ = "extracted_fields"
    
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("insurance_documents.id", ondelete="CASCADE"), nullable=False)
    field_name = Column(String(50), nullable=False)  # nom, prenom, cin, etc.
    field_value = Column(Text)
    confidence = Column(Float)  # 0.0 - 1.0
    is_valid = Column(Boolean, default=True)
    
    document = relationship("InsuranceDocument", back_populates="fields")
    
    __table_args__ = (
        UniqueConstraint("document_id", "field_name", name="uq_doc_field"),
    )


class DocumentAnomaly(Base):
    """Anomalie détectée dans un document ou entre documents."""
    __tablename__ = "document_anomalies"
    
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("insurance_documents.id", ondelete="CASCADE"), nullable=False)
    compared_with_doc_id = Column(Integer, ForeignKey("insurance_documents.id", ondelete="CASCADE"), nullable=True)
    anomaly_type = Column(String(50))  # identity_mismatch, contact_mismatch, etc.
    field_name = Column(String(50))
    severity = Column(String(20))  # critical, high, medium, low
    description = Column(Text)
    detected_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    
    document = relationship("InsuranceDocument", foreign_keys=[document_id], back_populates="anomalies")


class ComparisonSession(Base):
    """Session de comparaison entre plusieurs documents."""
    __tablename__ = "comparison_sessions"
    
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    document_ids = Column(Text)  # JSON array d'IDs
    match_score = Column(Float)
    is_same_person = Column(Boolean)
    summary = Column(Text)  # JSON


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions

def init_db():
    """Initialise la base de données."""
    Base.metadata.create_all(engine)


def save_insurance_document(
    filename: str,
    extraction_result: Dict[str, Any],
    mode: str = "replace"
) -> int:
    """
    Enregistre un document d'assurance extrait.
    
    Args:
        filename: Nom du fichier
        extraction_result: Résultat de l'extraction (champs, type doc, etc.)
        mode: 'replace' ou 'skip'
    
    Returns:
        ID du document créé/mis à jour
    """
    init_db()
    
    with SessionLocal() as session:
        # Vérifier si existe
        existing = (
            session.query(InsuranceDocument)
            .filter(InsuranceDocument.filename == filename)
            .order_by(InsuranceDocument.uploaded_at.desc())
            .first()
        )
        
        if existing and mode == "skip":
            return existing.id
        
        # Préparer les données
        fields_data = extraction_result.get("fields", {})
        completeness = extraction_result.get("completeness", 0.0)
        doc_type = extraction_result.get("document_type", "unknown")
        
        if existing and mode == "replace":
            # Mise à jour
            doc = existing
            doc.uploaded_at = dt.datetime.utcnow()
            doc.document_type = doc_type
            doc.completeness = completeness
            doc.json_data = json.dumps(extraction_result, ensure_ascii=False)
            
            # Supprimer anciens champs
            for field in doc.fields:
                session.delete(field)
            session.flush()
        else:
            # Création
            doc = InsuranceDocument(
                filename=filename,
                document_type=doc_type,
                completeness=completeness,
                json_data=json.dumps(extraction_result, ensure_ascii=False)
            )
            session.add(doc)
            session.flush()
        
        # Insérer les champs
        for field_name, field_data in fields_data.items():
            if isinstance(field_data, dict):
                value = field_data.get("value")
                confidence = field_data.get("confidence", 0.0)
                is_valid = field_data.get("found", True)
            else:
                value = field_data
                confidence = 0.5
                is_valid = bool(value)
            
            if value:  # Ne sauvegarder que les champs trouvés
                extracted_field = ExtractedField(
                    document_id=doc.id,
                    field_name=field_name,
                    field_value=str(value),
                    confidence=float(confidence),
                    is_valid=is_valid
                )
                session.add(extracted_field)
        
        session.commit()
        return doc.id


def save_anomalies(
    doc_id: int,
    anomalies: List[Dict[str, Any]],
    compared_with_id: Optional[int] = None
):
    """Enregistre les anomalies détectées."""
    init_db()
    
    with SessionLocal() as session:
        for anomaly in anomalies:
            db_anomaly = DocumentAnomaly(
                document_id=doc_id,
                compared_with_doc_id=compared_with_id,
                anomaly_type=anomaly.get("type", "unknown"),
                field_name=anomaly.get("field", ""),
                severity=anomaly.get("severity", "medium"),
                description=anomaly.get("message", "")
            )
            session.add(db_anomaly)
        
        session.commit()


def list_documents() -> List[InsuranceDocument]:
    """Liste tous les documents."""
    init_db()
    with SessionLocal() as session:
        return session.query(InsuranceDocument).order_by(
            InsuranceDocument.uploaded_at.desc()
        ).all()


def get_document(doc_id: int) -> Optional[InsuranceDocument]:
    """Récupère un document par ID."""
    init_db()
    with SessionLocal() as session:
        return session.get(InsuranceDocument, doc_id)


def get_document_dataframe(doc_id: int) -> pd.DataFrame:
    """Génère un DataFrame des champs extraits."""
    init_db()
    
    with SessionLocal() as session:
        doc = session.get(InsuranceDocument, doc_id)
        if not doc:
            return pd.DataFrame()
        
        rows = []
        for field in doc.fields:
            rows.append({
                "Champ": field.field_name,
                "Valeur": field.field_value,
                "Confiance": f"{field.confidence:.0%}",
                "Statut": "✓ Valide" if field.is_valid else "✗ Invalide"
            })
        
        return pd.DataFrame(rows)


def get_anomalies_dataframe(doc_id: int) -> pd.DataFrame:
    """Génère un DataFrame des anomalies."""
    init_db()
    
    with SessionLocal() as session:
        anomalies = (
            session.query(DocumentAnomaly)
            .filter(DocumentAnomaly.document_id == doc_id)
            .all()
        )
        
        if not anomalies:
            return pd.DataFrame()
        
        rows = []
        for anomaly in anomalies:
            rows.append({
                "Type": anomaly.anomaly_type,
                "Champ": anomaly.field_name,
                "Sévérité": anomaly.severity,
                "Description": anomaly.description,
                "Détecté le": anomaly.detected_at.strftime("%d/%m/%Y %H:%M")
            })
        
        return pd.DataFrame(rows)


def compare_documents_db(doc_ids: List[int]) -> Dict[str, Any]:
    """Compare plusieurs documents de la base."""
    init_db()
    
    with SessionLocal() as session:
        docs = [session.get(InsuranceDocument, doc_id) for doc_id in doc_ids]
        docs = [d for d in docs if d]  # Filtrer None
        
        if len(docs) < 2:
            return {"error": "Au moins 2 documents requis"}
        
        # Charger les données JSON
        doc_data = []
        for doc in docs:
            if doc.json_data:
                data = json.loads(doc.json_data)
                doc_data.append(data)
        
        return {
            "documents": [{"id": d.id, "filename": d.filename} for d in docs],
            "data": doc_data
        }
