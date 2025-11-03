# RAG System Setup Guide

This guide explains how to set up and use the RAG (Retrieval-Augmented Generation) system for recipe recommendations.

## Overview

The RAG system in dbwdi:
1. **Embedding Service**: Converts recipe text into vector embeddings
2. **Database**: Stores recipes with nutritional information
3. **Retrieval**: Finds similar recipes based on user queries
4. **Ranking**: Combines semantic similarity, nutritional fit, and ingredient overlap

## Prerequisites

1. Python 3.8+ with virtual environment activated
2. Database already seeded with recipes (run `python setup_rag.py`)

## Installation

1. Install the required dependency:
```bash
pip install sentence-transformers
```

2. Or reinstall all requirements:
```bash
cd backend
pip install -r requirements.txt
```

## Running the System

### 1. Start the Embedding Service

In a separate terminal, start the embedding service:

```bash
# From project root
python -m uvicorn backend.scripts.embed_service:app --host 127.0.0.1 --port 8001
```

Or using the script directly:

```bash
python backend/scripts/embed_service.py
```

The service should start and load the `all-MiniLM-L6-v2` model (first time will download ~80MB).

### 2. Start the Main API

In another terminal:

```bash
# From project root
cd backend
python -m uvicorn app.main:app --app-dir src --reload --host 127.0.0.1 --port 8000
```

**Note**: The `--app-dir src` flag is important - it tells uvicorn to treat the `src` directory as the root for imports, so `from app.core.config` works correctly.

### 3. Test the RAG System

You can test the system using the `/advisor/compose` endpoint:

```bash
curl -X POST "http://127.0.0.1:8000/advisor/compose" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "protein-rich breakfast smoothie bowl vegan",
    "servings": 1,
    "preferences": ["vegan"]
  }'
```

Or use the `/advisor/recommendations` endpoint:

```bash
curl "http://127.0.0.1:8000/advisor/recommendations?day=2025-01-15&body_weight_kg=70&goal=maintain&protein_g_per_kg=2.0&mode=rag&max_suggestions=3&vegan=true"
```

## How It Works

### Without Embedding Service (Fallback Mode)

If the embedding service is not running:
- The system uses **keyword matching** with tokenization
- Recipes are ranked by: keyword overlap + nutrition fit + ingredient overlap
- Still functional but less semantically aware

### With Embedding Service (Full RAG Mode)

When the embedding service is available:
- Query and recipes are converted to 384-dimensional vectors
- **Cosine similarity** finds semantically similar recipes
- Results are ranked by: semantic similarity + nutrition fit + ingredient overlap
- Much better at understanding user intent

## Configuration

The RAG system can be configured via environment variables or `.env` file:

```bash
# RAG Embedding Service URL
RAG_EMBED_URL=http://127.0.0.1:8001/embed

# Number of candidates to retrieve
RAG_TOP_K=30

# Maximum recipes to consider (0 = unlimited)
RAG_MAX_RECIPES=0

# LLM Configuration (for fallback generation)
OLLAMA_HOST=127.0.0.1
OLLAMA_PORT=11434
OLLAMA_MODEL=llama3.1
```

## Troubleshooting

### Embedding service won't start

**Error**: `ModuleNotFoundError: No module named 'sentence_transformers'`

**Solution**: Install the dependency:
```bash
pip install sentence-transformers
```

### No recipes returned

**Possible causes**:
1. Database not seeded - Run `python setup_rag.py`
2. Recipes don't match preferences - Check query preferences
3. Embedding service not running - Check http://127.0.0.1:8001/healthz

### Poor results

**Improvements**:
1. Check recipe tags in database
2. Ensure embedding service is using the latest model
3. Adjust `RAG_TOP_K` to retrieve more candidates
4. Use more specific preferences in queries

## Architecture

```
User Query → Build Query Text
               ↓
        Retrieve Candidates (Top K)
               ↓
        [With Embeddings] → Cosine Similarity
        [Without Embeddings] → Keyword Overlap
               ↓
        Score = Semantic + Nutrition + Ingredients
               ↓
        Rank & Return Top Results
```

## Next Steps

- Add more recipes to improve coverage
- Fine-tune embeddings with domain-specific data
- Implement caching for frequent queries
- Add user feedback loop for result quality

