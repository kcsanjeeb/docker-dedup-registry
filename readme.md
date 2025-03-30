# Docker Container Storage Repository Development Documentation

| Implementation | Folder | Date | Result | 
| --- | --- | --- | --- |
| Implementation 1 | - | 30 March, 2024 | - |

## 1. Overview
This storage repository is designed to receive and store Docker container images while supporting Docker-related protocols. Its core functionalities include:
- **Compatibility with Docker Registry API**, allowing Docker clients to push and pull images directly.
- **Layer-based storage**, managing Docker images according to their layered structure.
- **File extraction**, identifying and extracting individual files from each layer.
- **Block-level deduplication**, analyzing file content and performing block-level deduplication to optimize storage usage.

## 2. System Architecture
### 2.1 Component Breakdown
- **API Interface Layer**
  - **Input**: HTTP requests from Docker clients (image push/pull operations).
  - **Output**: Responses to Docker client requests, returning success/failure status and image data.
  - **Responsibilities**: Provides an interface compatible with the Docker Registry v2 API, processes HTTP requests, and forwards them to the storage management layer.

- **Storage Management Layer**
  - **Input**: Parsed Docker image data, including layer information and metadata.
  - **Output**: Structured storage of layers and metadata, preparing for deduplication.
  - **Responsibilities**: Parses the Docker image layer structure and converts it into a standard storage format.

- **Deduplication Engine**
  - **Input**: Layer data parsed by the storage management layer, including extracted file blocks.
  - **Output**: Stores only unique data blocks and returns a deduplicated storage index.
  - **Responsibilities**: Performs file-level and block-level deduplication to optimize storage space.

- **Storage Backend**
  - **Input**: Processes deduplicated data blocks and indexes.
  - **Output**: Stores data blocks and index files in the local file system.
  - **Responsibilities**: Efficiently manages and retrieves stored data blocks.

### 2.2 Data Flow
1. **Image Upload**: The Docker client pushes an image to the storage repository, and the API interface layer processes the request and passes it to the storage management layer.
2. **Layer Storage**: The storage management layer checks for existing layers and deduplicates them before storing.
3. **File Extraction**: Extracts files from image layers and computes deduplication-related information.
4. **Block-Level Deduplication Storage**: Splits files into fixed-size blocks and stores only unique blocks.
5. **Image Retrieval**: When the Docker client pulls an image, the storage repository reconstructs the layers and returns the data as needed.

## 3. Core Module Design
### 3.1 API Interface Layer
- **Input**: HTTP requests from Docker clients (PUT, GET).
- **Output**: Responds to Docker clients with HTTP status codes and data.
- **Responsibilities**:
  - Compatible with **Docker Registry v2 API**, handling requests from Docker clients.
  - Key API endpoints:
    - `PUT /v2/<name>/blobs/uploads/` - Upload image layers.
    - `GET /v2/<name>/manifests/<reference>` - Retrieve image manifests.
    - `GET /v2/<name>/blobs/<digest>` - Retrieve image layers.

### 3.2 Storage Management Layer
- **Input**: Image layer data received from the API interface layer.
- **Output**: Parsed layer data forwarded to the deduplication engine.
- **Responsibilities**:
  - Parses Docker image layers.
  - Extracts files from layers and records metadata (filename, size, hash value).
  - Maintains the mapping between layers and files.

### 3.3 Data Deduplication Engine
- **Input**: Extracted file data.
- **Output**: Deduplicated storage of file blocks and indexing.
- **Responsibilities**:
  - **Data Chunking (FASTCDC)**:
    - Uses the FastCDC variable-sized chunking algorithm to split data blocks based on content characteristics, improving deduplication efficiency.
    - Typical chunk sizes range from 4KB to 64KB.

  - **Hash Computation (SHA1)**:
    - Computes SHA1 hashes for data blocks to ensure uniqueness.
    - Hash values serve as block indices, preventing duplicate storage.

  - **Duplicate Block Identification**:
    - Quickly detects already stored blocks using hash indexes to avoid redundant storage.
    - Maintains a block index table mapping `<SHA1 hash, file offset>`.

  - **Container-Based Compression**:
    - Reduces redundant data in container images through deduplicated storage.
    - Stores only new or modified blocks, optimizing storage efficiency.
    

Example: Compute SHA1 hash.
```python
import hashlib

def hash_block(data):
    return hashlib.sha1(data).hexdigest()
```

### 3.4 Storage Backend (Local File System)
- **Input**: Deduplicated data blocks.
- **Output**: Stores unique data blocks in the local file system.
- **Responsibilities**:
  - Uses **hash-based file storage**, storing blocks based on their SHA1 hash values.
  - Maintains an index table for fast retrieval of stored blocks.
  - Maintains recipes for restoration of files and layers
  - Storage structure example:
```sh
/storage_repo/
 ├── layers/
 │   ├── layer1/
 │   		└── recipe and metadata ...
 │   ├── layer2/
 |			└── ...
 │   └── ...
 ├── blocks/
 │   ├── a1b2c3...
 │   ├── d4e5f6...
 │   └── ...
 └── index.db
```

## 4. Deployment and Usage
### 4.1 Running the Storage Repository
```sh
python storage_server.py
```
### 4.2 Pushing an Image
```sh
docker tag myimage localhost:5000/myimage
docker push localhost:5000/myimage
```
### 4.3 Pulling an Image
```sh
docker pull localhost:5000/myimage
```

## 5. Advanced Requirements
- **Delta Compression**:
  - Instead of only removing identical chunks, implement a delta compression mechanism to eliminate redundancies between similar chunks.
  - This would significantly reduce storage consumption.

- **Restore Optimization**:
  - Optimize the retrieval process to ensure faster restoration of images from deduplicated storage.
  - Techniques like preloading frequently accessed blocks and storage layout Optimizations can be used to enhance performance.

- **Selective Deduplication Mechanism**:
  - Implement policies to selectively deduplicate data based on predefined criteria such as file type, modification frequency, or storage tier.
  - This would allow balancing performance and deduplication efficiency depending on workload characteristics.