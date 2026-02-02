# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Tuple
from difflib import SequenceMatcher

from .insurance_const import REQUIRED_FIELDS, validate_field


class AnomalyDetector:
    """Détecte les anomalies et incohérences entre documents."""
    
    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold
    
    def compare_documents(self, doc1: Dict[str, Any], doc2: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare deux documents et détecte les anomalies.
        """
        anomalies = []
        warnings = []
        matches = []
        
        fields1 = doc1.get("fields", {})
        fields2 = doc2.get("fields", {})
        
        for field_name in REQUIRED_FIELDS:
            field1 = fields1.get(field_name, {})
            field2 = fields2.get(field_name, {})
            
            val1 = field1.get("value")
            val2 = field2.get("value")
            
            if not val1 or not val2:
                if val1 and not val2:
                    warnings.append({
                        "type": "missing_field",
                        "field": field_name,
                        "message": f"Champ '{field_name}' présent dans document 1 mais absent dans document 2",
                        "severity": "medium"
                    })
                elif val2 and not val1:
                    warnings.append({
                        "type": "missing_field",
                        "field": field_name,
                        "message": f"Champ '{field_name}' présent dans document 2 mais absent dans document 1",
                        "severity": "medium"
                    })
                continue
            
            # Comparaison des valeurs
            if field_name in ["nom", "prenom", "cin"]:
                # Champs d'identité : doivent être identiques
                if self._normalize_for_comparison(val1) != self._normalize_for_comparison(val2):
                    anomalies.append({
                        "type": "identity_mismatch",
                        "field": field_name,
                        "value1": val1,
                        "value2": val2,
                        "message": f"Identité différente pour '{field_name}': '{val1}' ≠ '{val2}'",
                        "severity": "critical"
                    })
                else:
                    matches.append({
                        "field": field_name,
                        "value": val1,
                        "match_type": "exact"
                    })
            
            elif field_name in ["telephone", "email", "adresse"]:
                # Champs de contact : similarité acceptable
                similarity = self._similarity(val1, val2)
                if similarity < self.similarity_threshold:
                    anomalies.append({
                        "type": "contact_mismatch",
                        "field": field_name,
                        "value1": val1,
                        "value2": val2,
                        "similarity": round(similarity, 2),
                        "message": f"Contact différent pour '{field_name}'",
                        "severity": "high" if similarity < 0.5 else "medium"
                    })
                else:
                    matches.append({
                        "field": field_name,
                        "value": val1,
                        "match_type": "similar",
                        "similarity": round(similarity, 2)
                    })
            
            elif field_name == "rib":
                # RIB : doit être identique
                if val1 != val2:
                    anomalies.append({
                        "type": "rib_mismatch",
                        "field": field_name,
                        "value1": val1,
                        "value2": val2,
                        "message": f"RIB différent entre les documents",
                        "severity": "high"
                    })
                else:
                    matches.append({
                        "field": field_name,
                        "value": val1,
                        "match_type": "exact"
                    })
            
            elif field_name in ["date_naissance", "date_effet", "date_echeance"]:
                # Dates : vérification de cohérence
                if val1 != val2:
                    warnings.append({
                        "type": "date_mismatch",
                        "field": field_name,
                        "value1": val1,
                        "value2": val2,
                        "message": f"Date différente pour '{field_name}'",
                        "severity": "medium"
                    })
                else:
                    matches.append({
                        "field": field_name,
                        "value": val1,
                        "match_type": "exact"
                    })
        
        # Calcul du score de correspondance
        total_fields = len(REQUIRED_FIELDS)
        match_score = len(matches) / total_fields if total_fields > 0 else 0
        
        # Vérifications croisées
        cross_checks = self._cross_validate(fields1, fields2)
        
        return {
            "anomalies": anomalies,
            "warnings": warnings,
            "matches": matches,
            "match_score": round(match_score, 2),
            "cross_checks": cross_checks,
            "summary": {
                "critical_anomalies": len([a for a in anomalies if a.get("severity") == "critical"]),
                "high_anomalies": len([a for a in anomalies if a.get("severity") == "high"]),
                "medium_warnings": len([w for w in warnings if w.get("severity") == "medium"]),
                "total_matches": len(matches),
                "is_same_person": len([a for a in anomalies if a.get("type") == "identity_mismatch"]) == 0
            }
        }
    
    def compare_multiple_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare plusieurs documents et détecte les incohérences."""
        if len(documents) < 2:
            return {"error": "Au moins 2 documents requis pour comparaison"}
        
        all_comparisons = []
        global_anomalies = []
        
        # Comparaison par paires
        for i in range(len(documents)):
            for j in range(i + 1, len(documents)):
                comparison = self.compare_documents(documents[i], documents[j])
                comparison["doc1_index"] = i
                comparison["doc2_index"] = j
                all_comparisons.append(comparison)
                
                # Anomalies critiques globales
                for anomaly in comparison["anomalies"]:
                    if anomaly.get("severity") == "critical":
                        global_anomalies.append({
                            **anomaly,
                            "doc1_index": i,
                            "doc2_index": j
                        })
        
        # Détection de patterns
        patterns = self._detect_patterns(documents)
        
        return {
            "total_documents": len(documents),
            "comparisons": all_comparisons,
            "global_anomalies": global_anomalies,
            "patterns": patterns,
            "recommendation": self._generate_recommendation(all_comparisons, global_anomalies)
        }
    
    def _normalize_for_comparison(self, value: str) -> str:
        """Normalise une valeur pour comparaison stricte."""
        if not value:
            return ""
        return value.upper().replace(" ", "").replace("-", "").replace(".", "")
    
    def _similarity(self, str1: str, str2: str) -> float:
        """Calcule la similarité entre deux chaînes."""
        if not str1 or not str2:
            return 0.0
        
        s1 = self._normalize_for_comparison(str1)
        s2 = self._normalize_for_comparison(str2)
        
        return SequenceMatcher(None, s1, s2).ratio()
    
    def _cross_validate(self, fields1: Dict, fields2: Dict) -> List[Dict[str, Any]]:
        """Effectue des vérifications croisées de cohérence."""
        checks = []
        
        # Vérification âge vs date de naissance
        dob1 = fields1.get("date_naissance", {}).get("value")
        dob2 = fields2.get("date_naissance", {}).get("value")
        
        if dob1 and dob2 and dob1 != dob2:
            checks.append({
                "check": "date_naissance_consistency",
                "status": "failed",
                "message": "Dates de naissance différentes détectées"
            })
        
        # Vérification cohérence email avec nom
        email1 = fields1.get("email", {}).get("value")
        nom1 = fields1.get("nom", {}).get("value")
        prenom1 = fields1.get("prenom", {}).get("value")
        
        if email1 and nom1 and prenom1:
            email_lower = email1.lower()
            if nom1.lower() not in email_lower and prenom1.lower() not in email_lower:
                checks.append({
                    "check": "email_name_consistency",
                    "status": "warning",
                    "message": "L'email ne semble pas correspondre au nom/prénom"
                })
        
        return checks
    
    def _detect_patterns(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Détecte des patterns suspects dans les documents."""
        patterns = {
            "duplicate_cin": [],
            "duplicate_rib": [],
            "same_contact_info": []
        }
        
        # Vérification des doublons
        cins = {}
        ribs = {}
        phones = {}
        
        for idx, doc in enumerate(documents):
            fields = doc.get("fields", {})
            
            cin = fields.get("cin", {}).get("value")
            if cin:
                if cin in cins:
                    patterns["duplicate_cin"].append({
                        "value": cin,
                        "doc_indices": [cins[cin], idx]
                    })
                else:
                    cins[cin] = idx
            
            rib = fields.get("rib", {}).get("value")
            if rib:
                if rib in ribs:
                    patterns["duplicate_rib"].append({
                        "value": rib,
                        "doc_indices": [ribs[rib], idx]
                    })
                else:
                    ribs[rib] = idx
        
        return patterns
    
    def _generate_recommendation(self, comparisons: List, anomalies: List) -> str:
        """Génère une recommandation basée sur l'analyse."""
        critical_count = len(anomalies)
        
        if critical_count == 0:
            return "✅ Tous les documents semblent cohérents. Aucune anomalie critique détectée."
        elif critical_count < 3:
            return f"⚠️ {critical_count} anomalie(s) critique(s) détectée(s). Vérification manuelle recommandée."
        else:
            return f"🚨 {critical_count} anomalies critiques détectées. Documents potentiellement frauduleux ou incohérents. Vérification approfondie requise."
