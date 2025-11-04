# RAG Modular Refactoring Summary

## Overview

The RAG (Retrieval-Augmented Generation) retrieval layer has been refactored into a modular architecture with three main components:

1. **Indexer** (`backend/src/app/rag/indexer.py`): Caches recipe embeddings in SQLite
2. **Preprocessor** (`backend/src/app/rag/preprocess.py`): Normalizes queries and documents before embedding
3. **Postprocessor** (`backend/src/app/rag/postprocess.py`): Applies scoring, filtering, and re-ranking

## Modified Files

### 1. Created: `backend/src/app/rag/__init__.py`
**Reason**: Module initialization with exports for the main classes

### 2. Created: `backend/src/app/rag/indexer.py`
**Reason**: 
- Implements `RecipeIndexer` class that caches recipe embeddings in SQLite table (`recipe_embeddings`)
- Provides `index_recipe()`, `batch_index()`, `refresh_recipe()`, `build_index()` methods
- Includes `RecipeEmbedding` SQLModel table for persistence
- Caches embeddings to avoid recomputing on every request

**Key Features**:
- Automatic table creation via `_ensure_table_exists()`
- Batch operations for efficiency
- Cache-first strategy (only computes missing embeddings)

### 3. Created: `backend/src/app/rag/preprocess.py`
**Reason**:
- Centralizes text normalization and tokenization logic
- `QueryPreprocessor.build_document()`: Converts Recipe objects to text for embedding
- `QueryPreprocessor.build_query_text()`: Builds normalized query from user request components
- Consistent text preprocessing across the system

**Key Features**:
- Normalizes whitespace and special characters
- Tokenization with German umlaut support
- Combines recipe metadata (title, tags, instructions, ingredients, macros) into document text

### 4. Created: `backend/src/app/rag/postprocess.py`
**Reason**:
- Separates scoring logic from retrieval logic
- Configurable scoring weights (semantic, nutrition, ingredient overlap)
- Supports both embedding-based and keyword-based scoring
- Provides filtering and re-ranking capabilities

**Key Features**:
- `PostProcessor.score_batch()`: Batch scoring with hybrid approach
- `PostProcessor.filter_by_constraints()`: Constraint-based filtering
- `PostProcessor.rerank()`: Result limiting and re-ranking

### 5. Modified: `backend/src/app/routers/advisor.py`
**Reason**:
- Refactored `_recipes_matching_query()` to use modular RAG components
- Maintains backward compatibility with legacy implementation (fallback if modules unavailable)
- Clear comments explaining behavior changes

**Key Changes**:
- Added imports for RAG modules
- `_recipes_matching_query()` now uses:
  - `QueryPreprocessor` for document and query building
  - `RecipeIndexer` for embedding caching
  - `PostProcessor` for scoring and ranking
- Embeds are cached in SQLite, significantly improving performance on subsequent requests

**Behavior Changes**:
- Recipe embeddings are now cached in `recipe_embeddings` table
- Document building uses `QueryPreprocessor.build_document()` instead of `_recipe_document()`
- Query building uses `QueryPreprocessor.build_query_text()` instead of `_build_query_text()`
- Scoring uses `PostProcessor.score_batch()` with configurable weights

### 6. Created: `backend/tests/integration/test_rag_modular.py`
**Reason**: Comprehensive test coverage for the modular RAG system

**Test Coverage**:
- **Indexer Tests**: Build/load, caching, batch operations, refresh, clear
- **Preprocessor Tests**: Text normalization, tokenization, document building, query building
- **Postprocessor Tests**: Cosine similarity, nutrition scoring, ingredient overlap, keyword overlap, batch scoring, filtering
- **End-to-End Tests**: Complete RAG pipeline from indexing to retrieval

**Test Results**: All 19 tests pass ✅

## Benefits

1. **Performance**: Embeddings are cached, avoiding recomputation on every request
2. **Modularity**: Clear separation of concerns (indexing, preprocessing, postprocessing)
3. **Testability**: Each component can be tested independently
4. **Maintainability**: Changes to one component don't affect others
5. **Extensibility**: Easy to add new scoring strategies or preprocessing steps
6. **Backward Compatibility**: Falls back to legacy implementation if modules unavailable

## Database Schema

New table: `recipe_embeddings`
- `recipe_id` (PK, FK to recipe.id)
- `embedding` (JSON array of floats)
- `document_text` (Text)
- `model_name` (String, default: "all-MiniLM-L6-v2")
- `updated_at` (DateTime)

Table is automatically created when `RecipeIndexer` is first used.

## Configuration

Scoring weights can be adjusted in `_recipes_matching_query()`:
```python
post_processor = PostProcessor(
    semantic_weight=1.0,      # Weight for embedding/keyword similarity
    nutrition_weight=0.5,     # Weight for nutrition fit score
    ingredient_weight=0.3,    # Weight for ingredient overlap
)
```

## Migration Notes

- No data migration required (embeddings will be computed on first use)
- Existing code continues to work (backward compatible)
- Legacy helper functions (`_recipe_document`, `_build_query_text`, etc.) are still available for fallback

## Testing

Run tests with:
```bash
cd backend
python -m pytest tests/integration/test_rag_modular.py -v
```

All tests pass successfully.
