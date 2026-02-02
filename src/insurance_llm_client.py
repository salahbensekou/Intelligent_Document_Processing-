# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, re
from typing import Dict, Any, Optional

from .insurance_const import ALL_FIELDS, FIELD_SYNONYMS


def make_insurance_extraction_prompt(page_text: str) -> str:
    """Crée le prompt pour l'extraction LLM des données d'assurance."""
    
    fields_desc = "\n".join([f"  - {field}: {', '.join(FIELD_SYNONYMS.get(field, [field]))}" 
                             for field in ALL_FIELDS])
    
    return f"""
Tu es un expert en extraction de données de documents d'assurance marocains.

OBJECTIF:
Extrais les informations suivantes du document fourni et renvoie STRICTEMENT un JSON valide.

CHAMPS À EXTRAIRE:
{fields_desc}

SCHÉMA DE SORTIE (JSON strict):
{{
  "fields": {{
    "nom": {{"value": "...", "confidence": 0.0-1.0}},
    "prenom": {{"value": "...", "confidence": 0.0-1.0}},
    "cin": {{"value": "...", "confidence": 0.0-1.0}},
    "date_naissance": {{"value": "JJ/MM/AAAA", "confidence": 0.0-1.0}},
    "telephone": {{"value": "...", "confidence": 0.0-1.0}},
    "email": {{"value": "...", "confidence": 0.0-1.0}},
    "adresse": {{"value": "...", "confidence": 0.0-1.0}},
    "rib": {{"value": "...", "confidence": 0.0-1.0}},
    "num_police": {{"value": "...", "confidence": 0.0-1.0}},
    "type_assurance": {{"value": "...", "confidence": 0.0-1.0}},
    "date_effet": {{"value": "JJ/MM/AAAA", "confidence": 0.0-1.0}},
    "date_echeance": {{"value": "JJ/MM/AAAA", "confidence": 0.0-1.0}}
  }},
  "document_type": "police_assurance|attestation_assurance|demande_souscription|...",
  "extraction_notes": "Notes sur l'extraction..."
}}

RÈGLES STRICTES:
1) JSON uniquement (pas de texte, pas de backticks)
2) Tu utilises UNIQUEMENT le TEXTE fourni (pas de connaissance externe)
3) Si un champ n'est pas explicitement présent dans le texte: value=null, confidence=0.0, found=false
4) Si plusieurs valeurs possibles OU ambiguïté: value=null, confidence=0.0, found=false
5) Si found=true, tu DOIS fournir "evidence": un extrait EXACT du texte (copié-collé) qui prouve la valeur
6) Normalisation formats (CIN, dates, tel, etc.) comme avant

{page_text[:8000]}
""".strip()


class InsuranceLLMClient:
    """Client LLM générique pour l'extraction d'assurance."""
    
    def __init__(self, api_key: Optional[str] = None, 
                 model: str = "gpt-4", 
                 temperature: float = 0.1):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.temperature = temperature
    
    def extract_fields(self, page_text: str) -> Dict[str, Any]:
        """
        Extrait les champs via LLM.
        À implémenter selon votre provider (OpenAI, Anthropic, etc.)
        """
        prompt = make_insurance_extraction_prompt(page_text)
        
       
# Version Gemini (compatible avec votre code existant)
class GeminiInsuranceClient:
    """Client Gemini pour extraction d'assurance."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            
            self.model = genai.GenerativeModel(
                model_name="gemini-1.5-pro",
                generation_config={
                    "temperature": 0.1,
                    "response_mime_type": "application/json"
                }
            )
        except Exception as e:
            raise RuntimeError(f"Erreur initialisation Gemini: {e}")
    
    def extract_fields(self, page_text: str) -> Dict[str, Any]:
        """Extrait les champs via Gemini."""
        prompt = make_insurance_extraction_prompt(page_text)
        
        try:
            response = self.model.generate_content(prompt)
            content = response.text
            
            data = json.loads(content)
            return data if isinstance(data, dict) else {"fields": {}}
            
        except Exception as e:
            return {
                "fields": {},
                "document_type": "unknown",
                "extraction_notes": f"Erreur Gemini: {str(e)}"
            }
