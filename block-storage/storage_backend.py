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

    def store_blob(self, file_path, digest):
        """Guaranteed chunk storage with verification"""
        # Ensure blocks directory exists and is writable
        self.blocks_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(str(self.blocks_dir), os.W_OK):
            raise RuntimeError(f"Blocks directory not writable: {self.blocks_dir}")

        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Verify digest
        computed = 'sha256:' + hashlib.sha256(content).hexdigest()
        if computed != digest:
            raise ValueError(f"Digest mismatch: {computed} != {digest}")

        blob_id = digest.replace('sha256:', '')
        blob_dir = self.layers_dir / blob_id
        blob_dir.mkdir(parents=True, exist_ok=True)

        # Store full content (required for Docker compatibility)
        (blob_dir / "data").write_bytes(content)
        
        # Now process chunks
        recipe = {"chunks": []}
        for i in range(0, len(content), 4096):  # 4KB chunks
            chunk = content[i:i+4096]
            chunk_hash = self._hash_block(chunk)
            recipe["chunks"].append(chunk_hash)
            
            # CRITICAL: Actually store each chunk
            chunk_path = self.blocks_dir / chunk_hash
            if not chunk_path.exists():
                try:
                    # Write with atomic rename to prevent corruption
                    temp_path = chunk_path.with_suffix('.tmp')
                    with open(temp_path, 'wb') as f:
                        f.write(chunk)
                    temp_path.rename(chunk_path)
                    self.index[chunk_hash] = True
                except Exception as e:
                    raise RuntimeError(f"Failed to store chunk {chunk_hash}: {str(e)}")

        # Save recipe
        (blob_dir / "recipe.json").write_text(json.dumps(recipe))
        
        # Verify all chunks were stored
        missing = [h for h in recipe['chunks'] if not (self.blocks_dir / h).exists()]
        if missing:
            raise RuntimeError(f"Missing chunks: {len(missing)}/{len(recipe['chunks'])}")
        
        return digest

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
        """Check if blob exists in any possible storage format"""
        if not digest.startswith('sha256:'):
            return False

        blob_id = digest.replace('sha256:', '')
        
        # Check all possible storage locations
        locations_to_check = [
            self.layers_dir / blob_id / "config",        # Config blob
            self.layers_dir / blob_id / "recipe.json",   # Recipe-based layer
            self.layers_dir / blob_id / "data",          # Legacy full blob
            self.blocks_dir / blob_id                    # Direct block storage
        ]
        
        return any(path.exists() for path in locations_to_check)

    def verify_storage(self):
        """Check storage integrity"""
        errors = []
        
        # Check blocks directory
        if not self.blocks_dir.exists():
            errors.append("Blocks directory missing")
        
        # Check sample layer
        for layer_dir in self.layers_dir.iterdir():
            recipe_file = layer_dir / "recipe.json"
            if not recipe_file.exists():
                continue
                
            with open(recipe_file) as f:
                recipe = json.load(f)
                
            for chunk_hash in recipe['chunks']:
                if not (self.blocks_dir / chunk_hash).exists():
                    errors.append(f"Missing chunk {chunk_hash} for layer {layer_dir.name}")
        
        return not bool(errors), errors