#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de test rapide pour le système d'extraction d'assurance
Lancez: python test_system.py
"""
from src.insurance_const import validate_field
from src.insurance_extractor import FieldExtractor
from src.anomaly_detector import AnomalyDetector
from src.insurance_db import init_db, save_insurance_document, list_documents

def test_validation():
    print("🧪 Test des validations de champs\n")
    tests = [
        ("cin", "AB123456", True),
        ("cin", "ab123456", True),
        ("cin", "123456", False),
        ("email", "test@example.com", True),
        ("email", "invalid-email", False),
        ("telephone", "0612345678", True),
        ("telephone", "+212612345678", True),
        ("telephone", "1234", False),
        ("rib", "123456789012345678901234", True),
        ("rib", "1234", False),
    ]
    for field, value, expected in tests:
        result = validate_field(field, value)
        status = "✅" if result == expected else "❌"
        print(f"{status} {field}: '{value}' -> {result} (attendu: {expected})")
    print()

def test_extraction():
    print("🧪 Test d'extraction de champs\n")
    sample_text = """
    POLICE D'ASSURANCE AUTO N° 2024-ABC-12345
    Informations de l'assuré:
    Nom: ALAMI
    Prénom: Mohammed
    CIN: AB123456
    Date de naissance: 15/03/1985
    Contact:
    Téléphone: 0612345678
    Email: m.alami@example.com
    Adresse: 123 Rue Hassan II, Casablanca
    Informations bancaires:
    RIB: 123456789012345678901234
    Détails du contrat:
    Type d'assurance: Auto tous risques
    Date d'effet: 01/01/2024
    Date d'échéance: 31/12/2024
    """
    extractor = FieldExtractor()
    results = extractor.extract_all_fields(sample_text)
    for field_name, field_data in results.items():
        if field_data.get("found"):
            print(f"✅ {field_name}: {field_data.get('value')} (confiance: {field_data.get('confidence', 0):.0%})")
        else:
            print(f"❌ {field_name}: Non trouvé")
    print()

def test_anomaly_detection():
    print("🧪 Test de détection d'anomalies\n")
    doc1 = {"fields": {"nom": {"value": "ALAMI", "confidence": 0.9}, "prenom": {"value": "Mohammed", "confidence": 0.9}, "cin": {"value": "AB123456", "confidence": 0.95}, "telephone": {"value": "0612345678", "confidence": 0.8}, "email": {"value": "m.alami@example.com", "confidence": 0.85}}}
    doc2_same = {"fields": {"nom": {"value": "ALAMI", "confidence": 0.9}, "prenom": {"value": "Mohammed", "confidence": 0.9}, "cin": {"value": "AB123456", "confidence": 0.95}, "telephone": {"value": "0612345678", "confidence": 0.8}, "email": {"value": "mohammed.alami@example.com", "confidence": 0.85}}}
    detector = AnomalyDetector()
    result1 = detector.compare_documents(doc1, doc2_same)
    print(f"Score de correspondance: {result1['match_score']:.0%}")
    print(f"Même personne: {result1['summary']['is_same_person']}")
    print()

def test_database():
    print("🧪 Test de la base de données\n")
    init_db()
    test_doc = {"fields": {"nom": {"value": "TEST", "confidence": 1.0, "found": True}, "prenom": {"value": "User", "confidence": 1.0, "found": True}, "cin": {"value": "AB123456", "confidence": 1.0, "found": True}}, "completeness": 0.5, "document_type": "test"}
    doc_id = save_insurance_document("test_document.pdf", test_doc)
    print(f"✅ Document test sauvegardé (ID: {doc_id})")
    docs = list_documents()
    print(f"✅ {len(docs)} document(s) dans la base\n")

if __name__ == "__main__":
    print("=" * 60)
    print("🔬 Tests du Système d'Extraction d'Assurance")
    print("=" * 60)
    test_validation()
    test_extraction()
    test_anomaly_detection()
    test_database()
    print("=" * 60)
    print("✨ Tests terminés!")
    print("=" * 60)
