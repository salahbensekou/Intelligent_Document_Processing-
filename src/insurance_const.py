# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from typing import List, Dict

# Champs obligatoires à extraire des documents d'assurance
REQUIRED_FIELDS = [
    "nom",
    "prenom", 
    "cin",
    "date_naissance",
    "telephone",
    "email",
    "adresse",
    "rib",
    "num_police",
    "type_assurance",
    "date_effet",
    "date_echeance",
]

# Champs optionnels
OPTIONAL_FIELDS = [
    "profession",
    "nationalite",
    "lieu_naissance",
    "situation_familiale",
    "beneficiaire",
    "montant_prime",
    "periodicite",
    "compagnie",
]

ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

# Patterns de validation
VALIDATION_PATTERNS = {
    "cin": re.compile(r"^[A-Z]{1,2}\d{5,8}$", re.I),
    "email": re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"),
    "telephone": re.compile(r"^(?:\+212|0)[5-7]\d{8}$"),
    "rib": re.compile(r"^\d{24}$"),
    "date": re.compile(r"^\d{2}[/-]\d{2}[/-]\d{4}$"),
}

# Synonymes pour la détection
FIELD_SYNONYMS: Dict[str, List[str]] = {
    "nom": ["nom", "nom de famille", "family name", "surname", "nom client"],
    "prenom": ["prénom", "prenom", "first name", "given name"],
    "cin": ["cin", "carte nationale", "cni", "carte d'identité", "identité nationale", "n° cin", "numero cin"],
    "date_naissance": ["date de naissance", "né(e) le", "date naissance", "birth date", "ddn"],
    "telephone": ["téléphone", "telephone", "tel", "tél", "gsm", "mobile", "phone", "contact"],
    "email": ["email", "e-mail", "courriel", "adresse email", "mail"],
    "adresse": ["adresse", "address", "domicile", "résidence"],
    "rib": ["rib", "relevé d'identité bancaire", "compte bancaire", "iban", "bank account"],
    "num_police": ["n° police", "numéro de police", "police n°", "contrat n°", "numero police", "policy number"],
    "type_assurance": ["type d'assurance", "type assurance", "produit", "formule", "garantie"],
    "date_effet": ["date d'effet", "date effet", "effective date", "début de garantie", "prise d'effet"],
    "date_echeance": ["date d'échéance", "date echeance", "échéance", "expiration", "fin de contrat"],
    "profession": ["profession", "activité professionnelle", "emploi", "métier"],
    "nationalite": ["nationalité", "nationalite", "nationality"],
    "lieu_naissance": ["lieu de naissance", "né à", "birthplace"],
    "situation_familiale": ["situation familiale", "marital status", "célibataire", "marié", "divorcé"],
    "beneficiaire": ["bénéficiaire", "beneficiaire", "beneficiary"],
    "montant_prime": ["prime", "montant prime", "cotisation", "premium"],
    "periodicite": ["périodicité", "periodicite", "fréquence", "mensuel", "annuel"],
    "compagnie": ["compagnie", "assureur", "société", "insurance company"],
}

# Types de documents d'assurance reconnus
INSURANCE_DOC_TYPES = [
    "police_assurance",
    "attestation_assurance", 
    "conditions_generales",
    "demande_souscription",
    "avenant",
    "bordereau",
    "quittance",
]

# Seuils de confiance
CONFIDENCE_THRESHOLDS = {
    "high": 0.85,
    "medium": 0.65,
    "low": 0.45,
}

def normalize_field_name(text: str) -> str:
    """Normalise un nom de champ détecté vers le nom standard."""
    text_lower = text.lower().strip()
    
    for standard_name, synonyms in FIELD_SYNONYMS.items():
        for syn in synonyms:
            if syn in text_lower:
                return standard_name
    
    return text_lower

def validate_field(field_name: str, value: str) -> bool:
    """Valide une valeur selon son type de champ."""
    if not value or not isinstance(value, str):
        return False
    
    value = value.strip()
    
    if field_name == "cin":
        return bool(VALIDATION_PATTERNS["cin"].match(value))
    elif field_name == "email":
        return bool(VALIDATION_PATTERNS["email"].match(value))
    elif field_name == "telephone":
        clean = value.replace(" ", "").replace("-", "").replace(".", "")
        return bool(VALIDATION_PATTERNS["telephone"].match(clean))
    elif field_name == "rib":
        clean = value.replace(" ", "").replace("-", "")
        return bool(VALIDATION_PATTERNS["rib"].match(clean))
    elif field_name in ["date_naissance", "date_effet", "date_echeance"]:
        return bool(VALIDATION_PATTERNS["date"].match(value))
    
    return len(value) > 0
