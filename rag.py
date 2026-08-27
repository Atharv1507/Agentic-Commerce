import json
import logging
from typing import Optional

import chromadb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = chromadb.Client()
collection = client.create_collection(name="products")


def load_catalog() -> int:
    """Load products from catalog.json into ChromaDB.

    Returns:
        Number of products loaded.
    """
    with open("catalog.json", "r") as f:
        products = json.load(f)

    collection.add(
        ids=[p["id"] for p in products],
        documents=[p["description"] for p in products],
        metadatas=[
            {
                "name": p["name"],
                "brand": p["brand"],
                "price": p["price"],
                "color": p["color"],
                "gender": p["gender"],
            }
            for p in products
        ],
    )

    logger.info(f"Loaded {len(products)} products into ChromaDB")
    return len(products)


load_catalog()


def search_catalog(
    query: str,
    top_k: int = 3,
    max_price: Optional[int] = None,
    gender: Optional[str] = None,
) -> list[dict]:
    """Search product catalog using semantic similarity with optional filters.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return.
        max_price: Maximum price filter in INR.
        gender: Gender filter (Men, Women, Unisex).

    Returns:
        List of matching products.
    """
    try:
        results = collection.query(query_texts=[query], n_results=top_k * 2)

        if not results["ids"][0]:
            logger.info(f"No results for query: {query}")
            return []

        products = []
        for i, pid in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]

            if max_price and meta["price"] > max_price:
                continue
            if (
                gender
                and meta["gender"].lower() != gender.lower()
                and meta["gender"].lower() != "unisex"
            ):
                continue

            products.append(
                {
                    "id": pid,
                    "name": meta["name"],
                    "brand": meta["brand"],
                    "price": meta["price"],
                    "color": meta["color"],
                    "gender": meta["gender"],
                    "description": results["documents"][0][i],
                }
            )

            if len(products) >= top_k:
                break

        logger.info(f"Query '{query}' returned {len(products)} products")
        return products

    except Exception as e:
        logger.error(f"Search error: {e}")
        return []


def get_product_by_id(product_id: str) -> Optional[dict]:
    """Get a single product by ID.

    Args:
        product_id: The product ID to lookup.

    Returns:
        Product dict if found, None otherwise.
    """
    try:
        result = collection.get(ids=[product_id], include=["documents", "metadatas"])
        if not result["ids"]:
            return None

        meta = result["metadatas"][0]
        return {
            "id": product_id,
            "name": meta["name"],
            "brand": meta["brand"],
            "price": meta["price"],
            "color": meta["color"],
            "gender": meta["gender"],
            "description": result["documents"][0],
        }
    except Exception:
        return None
