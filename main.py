from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import chromadb
import json
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title="Seller Agent")

# ChromaDB setup
chroma_client = chromadb.Client()
collection = chroma_client.create_collection(name="products")

# Load catalog
def load_catalog():
    with open("catalog.json", "r") as f:
        products = json.load(f)
    
    # Add to ChromaDB
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
    print(f"Loaded {len(products)} products into ChromaDB")

load_catalog()

class QueryRequest(BaseModel):
    query: str
    max_price: int = None
    top_k: int = 5

@app.post("/query")
async def query_products(request: QueryRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    results = collection.query(
        query_texts=[request.query],
        n_results=request.top_k
    )
    
    if not results["ids"][0]:
        return {"status": "no_match", "message": "No matching products found", "products": []}
    
    products = []
    for i, pid in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        product = {
            "id": pid,
            "name": meta["name"],
            "brand": meta["brand"],
            "price": meta["price"],
            "color": meta["color"],
            "gender": meta["gender"],
            "description": results["documents"][0][i]
        }
        
        # Budget filter
        if request.max_price and meta["price"] > request.max_price:
            continue
        
        products.append(product)
    
    if not products:
        return {"status": "no_match", "message": "No products within budget", "products": []}
    
    return {"status": "success", "products": products}

@app.get("/products/{product_id}")
async def get_product(product_id: str):
    try:
        result = collection.get(ids=[product_id], include=["documents", "metadatas"])
        if not result["ids"]:
            raise HTTPException(status_code=404, detail="Product not found")
        
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
    except Exception as e:
        raise HTTPException(status_code=404, detail="Product not found")

@app.get("/health")
async def health():
    return {"status": "ok", "products_loaded": collection.count()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
