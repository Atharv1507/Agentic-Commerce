import json
import chromadb

client = chromadb.Client()
collection = client.create_collection(name="products")

def load_catalog():
    with open("catalog.json", "r") as f:
        products = json.load(f)
    
    collection.add(
        ids=[p["id"] for p in products],
        documents=[p["description"] for p in products],
        metadatas=[{
            "name": p["name"],
            "brand": p["brand"],
            "price": p["price"],
            "color": p["color"],
            "gender": p["gender"]
        } for p in products]
    )
    return len(products)

load_catalog()

def search_catalog(query: str, top_k: int = 3, max_price: int = None, gender: str = None) -> list:
    """Search product catalog using semantic similarity with optional filters."""
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k * 2
        )
        
        if not results["ids"][0]:
            return []
        
        products = []
        for i, pid in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            
            if max_price and meta["price"] > max_price:
                continue
            if gender and meta["gender"].lower() != gender.lower() and meta["gender"].lower() != "unisex":
                continue
            
            products.append({
                "id": pid,
                "name": meta["name"],
                "brand": meta["brand"],
                "price": meta["price"],
                "color": meta["color"],
                "gender": meta["gender"],
                "description": results["documents"][0][i]
            })
            
            if len(products) >= top_k:
                break
        
        return products
    except Exception as e:
        print(f"Search error: {e}")
        return []

def get_product_by_id(product_id: str) -> dict | None:
    """Get a single product by ID."""
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
            "description": result["documents"][0]
        }
    except:
        return None
