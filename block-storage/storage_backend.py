import os
import json
import hashlib
from pathlib import Path

class DedupStorage:
    def __init__(self, repo_root="data"):
        # Convert to Path object if not already
        self.repo_root = Path(repo_root)
        # Ensure main data directory exists
        self.repo_root.mkdir(parents=True, exist_ok=True)
        # Define all required subdirectories
        self.blocks_dir = self.repo_root / "blocks"
        self.layers_dir = self.repo_root / "layers"
        self.manifests_dir = self.repo_root / "manifests"
        self.uploads_dir = self.repo_root / "uploads"
        # List of all directories to create
        required_dirs = [
            self.blocks_dir,
            self.layers_dir,
            self.manifests_dir,
            self.uploads_dir
        ]
        # Create each directory if it doesn't exist
        for directory in required_dirs:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                print(f"Verified directory: {directory}")  # Optional debug output
            except Exception as e:
                raise RuntimeError(
                    f"Failed to create directory {directory}: {str(e)}"
                ) from e
        # Initialize block index
        self.index = {}  # Tracks stored blocks {hash: path}
        # Load existing blocks into index
        self._load_existing_blocks()
    
    def _load_existing_blocks(self):
        """Pre-populate index with existing blocks"""
        if self.blocks_dir.exists():
            for block_file in self.blocks_dir.iterdir():
                if block_file.is_file():
                    self.index[block_file.name] = block_file

    def _chunk_file(self, file_path, chunk_size=4096):
        """Improved chunking that handles small files"""
        file_size = os.path.getsize(file_path)
        
        # For files smaller than 2 chunks, don't chunk
        if file_size <= chunk_size * 2:
            with open(file_path, 'rb') as f:
                yield f.read()
            return
            
        # Normal chunking for larger files
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                yield chunk

    def _hash_block(self, data):
        """Generate SHA-1 hash for a data block"""
        return hashlib.sha1(data).hexdigest()

    def store_block(self, data):
        """Store a data block with deduplication"""
        chunk_hash = self._hash_block(data)
        if chunk_hash not in self.index:
            block_path = self.blocks_dir / chunk_hash
            block_path.write_bytes(data)
            self.index[chunk_hash] = block_path
        return chunk_hash

    def store_layer(self, upload_path, digest):
        # Read content once
        with open(upload_path, 'rb') as f:
            content = f.read()
        
        # Verify digest
        computed = 'sha256:' + hashlib.sha256(content).hexdigest()
        if computed != digest:
            raise ValueError(f"Digest mismatch: {computed} != {digest}")

        layer_dir = self.layers_dir / digest.replace('sha256:', '')
        if layer_dir.exists():
            return digest  # Already exists

        layer_dir.mkdir(parents=True, exist_ok=True)
        
        # ONLY store chunks (no full layer copy)
        recipe = {"chunks": []}
        for i in range(0, len(content), 4096):  # 4KB chunks
            chunk = content[i:i+4096]
            chunk_hash = self._hash_block(chunk)
            recipe["chunks"].append(chunk_hash)
            
            if chunk_hash not in self.index:
                (self.blocks_dir / chunk_hash).write_bytes(chunk)
                self.index[chunk_hash] = True
        
        # Store just the recipe
        (layer_dir / "recipe.json").write_text(json.dumps(recipe))
        
        return digest  # No full "data" file written
    
    def layer_exists(self, digest):
        """Check if layer exists (by digest)"""
        return (self.layers_dir / digest.replace('sha256:', '')).exists()

    def get_blob(self, digest):
        """Retrieve a stored blob"""
        # Try blocks first
        block_path = self.blocks_dir / digest.replace('sha256:', '')
        if block_path.exists():
            return block_path.read_bytes()
        
        # Then try layers
        layer_path = self.layers_dir / digest.replace('sha256:', '') / "data"
        if layer_path.exists():
            return layer_path.read_bytes()
        
        return None

    def store_manifest(self, name, reference, manifest_data):
        """Store image manifest"""
        manifest_dir = self.manifests_dir / name
        manifest_dir.mkdir(parents=True, exist_ok=True)
        
        # Store by both reference and digest
        manifest_path = manifest_dir / reference
        manifest_path.write_bytes(manifest_data)
        
        # Also store by digest
        manifest_digest = 'sha256:' + hashlib.sha256(manifest_data).hexdigest()
        digest_path = manifest_dir / manifest_digest
        if not digest_path.exists():
            digest_path.write_bytes(manifest_data)
        
        return manifest_digest

    def store_blob(self, file_path, digest):
        """Store a blob with strict digest verification and deduplication"""
        # Read the entire file first for digest verification
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Verify the digest matches exactly
        computed_digest = 'sha256:' + hashlib.sha256(content).hexdigest()
        if computed_digest != digest:
            raise ValueError(f"Digest verification failed: expected {digest}, got {computed_digest}")

        # Check if we already have this blob
        blob_dir = self.layers_dir / digest.replace('sha256:', '')
        if blob_dir.exists():
            return digest

        # Create directory for this blob
        blob_dir.mkdir(parents=True, exist_ok=True)

        # Store using deduplication
        recipe = {"chunks": []}
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(4096)  # 4KB chunks
                if not chunk:
                    break
                chunk_hash = self._hash_block(chunk)
                if chunk_hash not in self.index:
                    (self.blocks_dir / chunk_hash).write_bytes(chunk)
                    self.index[chunk_hash] = True
                recipe["chunks"].append(chunk_hash)

        # Save the recipe
        (blob_dir / "recipe.json").write_text(json.dumps(recipe))
        
        # Store the full content for compatibility
        (blob_dir / "data").write_bytes(content)
        
        return digest

    def blob_exists(self, digest):
        """Check if blob exists in either form"""
        # Check full blob storage
        blob_path = self.layers_dir / digest.replace('sha256:', '') / "data"
        if blob_path.exists():
            return True
            
        # Check if we could reconstruct from blocks
        recipe_path = self.layers_dir / digest.replace('sha256:', '') / "recipe.json"
        if recipe_path.exists():
            return True
            
        return False