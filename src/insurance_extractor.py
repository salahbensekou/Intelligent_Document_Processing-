# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from .insurance_const import (
    ALL_FIELDS, FIELD_SYNONYMS, VALIDATION_PATTERNS,
    normalize_field_name, validate_field
)

# Patterns de détection robustes
class FieldExtractor:
    
    def __init__(self):
        self.patterns = self._build_patterns()
    
    def _build_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Construit les patterns regex pour chaque champ."""
        return {
            "nom": [
                re.compile(r"(?:nom|surname|family\s*name)\s*:?\s*([A-ZÀ-Ÿ][A-ZÀ-Ÿ\s-]{1,40})", re.I),
                re.compile(r"M\.?\s+([A-ZÀ-Ÿ][A-ZÀ-Ÿ\s-]{2,30})\s+[A-ZÀ-Ÿ][a-zà-ÿ]", re.I),
            ],
            "prenom": [
                re.compile(r"(?:prénom|prenom|first\s*name|given\s*name)\s*:?\s*([A-ZÀ-Ÿ][a-zà-ÿ-]{1,30})", re.I),
                re.compile(r"M\.?\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ\s-]+\s+([A-ZÀ-Ÿ][a-zà-ÿ-]{2,25})", re.I),
            ],
            "cin": [
                re.compile(r"(?:CIN|CNI|carte\s*(?:nationale|d'identité))\s*:?\s*N?°?\s*([A-Z]{1,2}\d{5,8})", re.I),
                re.compile(r"\b([A-Z]{1,2}\d{6,8})\b"),
            ],
            "date_naissance": [
                re.compile(r"(?:date\s*de\s*naissance|né(?:e)?\s*le|birth\s*date|ddn)\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})", re.I),
                re.compile(r"(?:né(?:e)?\s*le)\s*:?\s*(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4})", re.I),
            ],
            "telephone": [
                re.compile(r"(?:tél(?:éphone)?|tel|gsm|mobile|phone)\s*:?\s*((?:\+212|0)[5-7]\d[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2})", re.I),
                re.compile(r"\b(0[5-7]\d{8})\b"),
            ],
            "email": [
                re.compile(r"(?:e?mail|courriel)\s*:?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", re.I),
                re.compile(r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b"),
            ],
            "adresse": [
                re.compile(r"(?:adresse|domicile|résidence)\s*:?\s*([^\n]{10,100})", re.I),
                re.compile(r"\d+[\s,]+(?:rue|avenue|bd|boulevard|impasse|allée)[^\n]{5,80}", re.I),
            ],
            "rib": [
                re.compile(r"(?:RIB|IBAN|compte)\s*:?\s*([0-9\s-]{20,34})", re.I),
                re.compile(r"\b(\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})\b"),
            ],
            "num_police": [
                re.compile(r"(?:police|contrat)\s*N?°?\s*:?\s*([A-Z0-9/-]{5,20})", re.I),
                re.compile(r"(?:N°\s*police|policy\s*number)\s*:?\s*([A-Z0-9/-]{5,20})", re.I),
            ],
            "type_assurance": [
                re.compile(r"(?:type\s*d'assurance|produit|formule)\s*:?\s*([^\n]{5,50})", re.I),
                re.compile(r"(?:assurance|garantie)\s+(auto|vie|santé|habitation|multirisque)", re.I),
            ],
            "date_effet": [
                re.compile(r"(?:date\s*d'effet|effective\s*date|début)\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})", re.I),
                re.compile(r"(?:prise\s*d'effet|à\s*effet\s*du)\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})", re.I),
            ],
            "date_echeance": [
                re.compile(r"(?:échéance|expiration|fin\s*de\s*contrat)\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})", re.I),
                re.compile(r"(?:valable\s*jusqu'au)\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})", re.I),
            ],
        }
    
    def extract_field(self, text: str, field_name: str) -> Optional[Tuple[str, float]]:
        """
        Extrait un champ spécifique du texte.
        Retourne (valeur, confiance) ou None.
        """
        if field_name not in self.patterns:
            return None
        
        for pattern in self.patterns[field_name]:
            matches = pattern.findall(text)
            if matches:
                value = matches[0].strip() if isinstance(matches[0], str) else matches[0][0].strip()
                
                # Nettoyage spécifique par type
                value = self._clean_value(field_name, value)
                
                # Validation
                if validate_field(field_name, value):
                    confidence = self._calculate_confidence(field_name, value, pattern)
                    return (value, confidence)
        
        return None
    
    def _clean_value(self, field_name: str, value: str) -> str:
        """Nettoie une valeur extraite selon son type."""
        value = value.strip()
        
        if field_name in ["telephone", "rib"]:
            value = re.sub(r"[\s.-]", "", value)
        
        elif field_name == "cin":
            value = value.upper().replace(" ", "")
        
        elif field_name == "email":
            value = value.lower()
        
        elif field_name in ["nom"]:
            value = value.upper()
        
        elif field_name in ["prenom"]:
            value = value.title()
        
        return value
    
    def _calculate_confidence(self, field_name: str, value: str, pattern: re.Pattern) -> float:
        """Calcule la confiance de l'extraction."""
        base_confidence = 0.7
        
        # Boost si le pattern contient le nom du champ
        if any(syn in pattern.pattern.lower() for syn in FIELD_SYNONYMS.get(field_name, [])):
            base_confidence += 0.15
        
        # Boost si validation stricte passe
        if field_name in ["cin", "email", "telephone", "rib"]:
            if validate_field(field_name, value):
                base_confidence += 0.15
        
        return min(base_confidence, 1.0)
    
    def extract_all_fields(self, text: str) -> Dict[str, Any]:
        """Extrait tous les champs possibles d'un texte."""
        results = {}
        
        for field in ALL_FIELDS:
            extraction = self.extract_field(text, field)
            if extraction:
                value, confidence = extraction
                results[field] = {
                    "value": value,
                    "confidence": confidence,
                    "found": True
                }
            else:
                results[field] = {
                    "value": None,
                    "confidence": 0.0,
                    "found": False
                }
        
        return results


def extract_insurance_data(page_text: str) -> Dict[str, Any]:
    """
    Fonction principale d'extraction des données d'assurance.
    """
    extractor = FieldExtractor()
    fields = extractor.extract_all_fields(page_text)
    
    # Calcul de la complétude
    required_found = sum(1 for f in fields.values() if f["found"])
    completeness = required_found / len(ALL_FIELDS)
    
    # Détection du type de document
    doc_type = _detect_document_type(page_text)
    
    return {
        "fields": fields,
        "completeness": completeness,
        "document_type": doc_type,
        "extraction_timestamp": datetime.now().isoformat(),
    }


def _detect_document_type(text: str) -> str:
    """Détecte le type de document d'assurance."""
    text_lower = text.lower()
    
    if "police d'assurance" in text_lower or "contrat d'assurance" in text_lower:
        return "police_assurance"
    elif "attestation" in text_lower:
        return "attestation_assurance"
    elif "conditions générales" in text_lower or "conditions particulières" in text_lower:
        return "conditions_generales"
    elif "demande de souscription" in text_lower or "bulletin d'adhésion" in text_lower:
        return "demande_souscription"
    elif "avenant" in text_lower:
        return "avenant"
    elif "quittance" in text_lower or "reçu" in text_lower:
        return "quittance"
    else:
        return "unknown"
