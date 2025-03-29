# Efficient Docker Registry with Block-Level Deduplication

## Project Description:
This project implements a custom Docker registry that optimizes storage efficiency through block-level deduplication. Unlike traditional registries (which store redundant layers in full), this system:

* **Chunks Image Layers into Blocks:**
    * Splits layers into fixed-size blocks (e.g., 4KB) and computes SHA-1 hashes for uniqueness.
    * Only stores unique blocks, eliminating duplicates across images.

* **Maintains Compatibility:**
    * Supports standard Docker Registry API (/v2/ endpoints).
    * Works with docker push/pull commands without client-side changes.

* **Key Efficiency Gains:**
    * Storage Savings: Up to 70% reduction for similar images (e.g., Ubuntu/Nginx variants).
    * Network Efficiency: Transfers only unique blocks during pulls.
    * Scalability: Indexed storage allows fast lookups even with millions of blocks.

* **Demonstrated Workflow:**
    * Built/tested with Alpine and Ubuntu-based Nginx images.
    * Compared against a traditional registry (registry:2), showing:
        * Traditional: Stores full layers → Linear storage growth.
        * Dedup: Stores unique blocks → Sublinear growth.

* **Technical Components:**
    * Python/Flask: Mimics Docker Registry API.
    * Content-Defined Chunking: Uses fixed-size blocks (extendable to variable-sized).
    * Local Filesystem Backend: Stores blocks in ./data/blocks/ with layer recipes.

## Why It Matters:
* Ideal for CI/CD pipelines with frequent image updates.
* Reduces costs for private registries (cloud/on-premise).
* Transparent to end users—no Docker client changes needed.

## Future Enhancements:
* Add variable-sized chunking (e.g., FastCDC).
* Support cloud storage backends (S3, Ceph).
* Implement garbage collection for orphaned blocks.
* This project bridges the gap between Docker's layer-based storage and enterprise-grade deduplication systems, offering efficiency without sacrificing compatibility.

### Example Scenario
* Image A (Base Image):
    * app.py → Blocks: B1, B2
    * lib.so → Blocks: B3, B4
* Image B (Updated Image):
    * app.py → Blocks: B1, B5 (modified)
    * lib.so → Reuses B3, B4
* Storage Savings:
    * Without deduplication: 4 + 4 = 8 blocks.
    * With deduplication: 5 blocks (shared B1, B3, B4).

##  🚀 Quick Start
### 1. Clone the Project
```bash
git clone https://github.com/your-repo/docker-dedup-registry.git
cd docker-dedup-registry
```
### 2. Install Dependencies
```bash
pip install -r requirements.txt  # Flask, hashlib, etc.
```
### 3. Run the Dedup Registry
```bash
python registry_api.py  # Starts on http://localhost:5001
```
### 4. Run a Traditional Registry (for Comparison)
```bash
docker run -d -p 5000:5000 --name traditional-registry registry:2
```
## 🔍 Demo: Compare Storage Efficiency
### 1. Build Test Images
```bash
# Ubuntu-based Nginx images (modify index.html)
docker build -t nginx-v1 -f nginx-v1/Dockerfile .
docker build -t nginx-v2 -f nginx-v2/Dockerfile .
```
### 2. Push to Both Registries
```bash
# Traditional (stores full layers)
docker tag nginx-v1 localhost:5000/nginx-v1
docker tag nginx-v2 localhost:5000/nginx-v2
docker push localhost:5000/nginx-v1
docker push localhost:5000/nginx-v2

# Dedup (stores unique blocks)
docker tag nginx-v1 localhost:5001/nginx-v1
docker tag nginx-v2 localhost:5001/nginx-v2
docker push localhost:5001/nginx-v1
docker push localhost:5001/nginx-v2
```
### 3. Compare Storage Usage
```bash
# Traditional registry (stores full copies)
docker exec traditional-registry du -sh /var/lib/registry
# Expected: ~150MB+ (Ubuntu base layers stored twice)

# Dedup registry (stores unique blocks)
du -sh data/blocks
# Expected: ~50MB (shared base + only new HTML changes)
```

## 📊 How It Works
1. Chunking & Deduplication
    * Splits layers into 4KB blocks and computes SHA-1 hashes.
    * Only stores unique blocks (e.g., Ubuntu’s base layers stored once).

2. Layer Reconstruction
    * Uses recipes (recipe.json) to rebuild layers from blocks during docker pull.

3. API Compatibility
    * Implements Docker Registry API (/v2/) for seamless integration.

## 📂 Project Structure
```bash
docker-dedup-registry/
├── registry_api.py       # Docker Registry API server (Flask)
├── storage_backend.py    # Deduplication logic
├── data/                 # Storage
│   ├── blocks/           # Unique chunks (SHA-1 named)
│   ├── layers/           # Layer metadata
│   └── uploads/          # Temporary uploads
├── nginx-v1/             # Test image 1
│   └── Dockerfile        # FROM ubuntu + custom HTML
├── nginx-v2/             # Test image 2
│   └── Dockerfile        # Modified HTML
└── requirements.txt      # Python dependencies
```
