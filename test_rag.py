#!/usr/bin/env python
"""
Simple test script to verify RAG system is working.
Run this after starting both the embedding service and main API.
"""

import requests
import json
from datetime import date

# Configuration
EMBED_URL = "http://127.0.0.1:8001/healthz"
API_URL = "http://127.0.0.1:8000"
COMPOSE_ENDPOINT = f"{API_URL}/advisor/compose"
RECOMMENDATIONS_ENDPOINT = f"{API_URL}/advisor/recommendations"

def test_embed_service():
    """Test if embedding service is running."""
    print("Testing embedding service...")
    try:
        response = requests.get(EMBED_URL, timeout=2)
        if response.status_code == 200:
            print("✓ Embedding service is running")
            return True
        else:
            print(f"✗ Embedding service returned status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Embedding service not reachable: {e}")
        print("  Make sure to start it with: python -m uvicorn backend.scripts.embed_service:app --host 127.0.0.1 --port 8001")
        return False

def test_api_health():
    """Test if main API is running."""
    print("\nTesting main API...")
    try:
        response = requests.get(f"{API_URL}/health", timeout=2)
        if response.status_code == 200:
            print("✓ Main API is running")
            return True
        else:
            print(f"✗ Main API returned status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Main API not reachable: {e}")
        print("  Make sure to start it with: cd backend && python -m uvicorn app.main:app --app-dir src --reload")
        return False

def test_compose_with_rag():
    """Test /advisor/compose endpoint with RAG."""
    print("\nTesting /advisor/compose with RAG...")
    
    payload = {
        "message": "protein-rich breakfast smoothie bowl vegan",
        "servings": 1,
        "preferences": ["vegan"]
    }
    
    try:
        response = requests.post(COMPOSE_ENDPOINT, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            print("✓ Compose endpoint successful")
            print(f"  Returned {len(data.get('ideas', []))} recipe ideas")
            if data.get('notes'):
                print(f"  Notes: {data['notes']}")
            
            # Check if RAG was used
            for idea in data.get('ideas', []):
                print(f"\n  Idea: {idea.get('title')}")
                print(f"    Source: {idea.get('source')}")
                if idea.get('macros'):
                    print(f"    Macros: {idea['macros']['kcal']:.0f} kcal, {idea['macros']['protein_g']:.1f}g protein")
            return True
        else:
            print(f"✗ Compose endpoint failed: {response.status_code}")
            print(f"  Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed: {e}")
        return False

def test_recommendations_with_rag():
    """Test /advisor/recommendations endpoint with RAG."""
    print("\nTesting /advisor/recommendations with RAG...")
    
    today = date.today().isoformat()
    params = {
        "day": today,
        "body_weight_kg": 70,
        "goal": "maintain",
        "protein_g_per_kg": 2.0,
        "mode": "rag",
        "max_suggestions": 3,
        "vegan": "true"
    }
    
    try:
        response = requests.get(RECOMMENDATIONS_ENDPOINT, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            print("✓ Recommendations endpoint successful")
            print(f"  Mode: {data.get('mode')}")
            print(f"  Returned {len(data.get('suggestions', []))} suggestions")
            
            for suggestion in data.get('suggestions', [])[:3]:
                print(f"\n  Suggestion: {suggestion.get('name')}")
                print(f"    Source: {suggestion.get('source')}")
                if suggestion.get('est_kcal'):
                    print(f"    Estimated: {suggestion['est_kcal']:.0f} kcal")
            return True
        else:
            print(f"✗ Recommendations endpoint failed: {response.status_code}")
            print(f"  Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed: {e}")
        return False

def main():
    print("=" * 60)
    print("RAG System Test")
    print("=" * 60)
    
    results = []
    
    # Test embedding service
    embed_ok = test_embed_service()
    results.append(("Embed Service", embed_ok))
    
    # Test main API
    api_ok = test_api_health()
    results.append(("Main API", api_ok))
    
    # Only test endpoints if both services are up
    if embed_ok and api_ok:
        # Test compose
        compose_ok = test_compose_with_rag()
        results.append(("Compose Endpoint", compose_ok))
        
        # Test recommendations
        rec_ok = test_recommendations_with_rag()
        results.append(("Recommendations Endpoint", rec_ok))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(result for _, result in results)
    if all_passed:
        print("\n🎉 All tests passed! RAG system is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    exit(main())

