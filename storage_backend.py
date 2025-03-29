import os
import json
import hashlib
from pathlib import Path

class DedupStorage:
    def __init__(self, repo_root="data"):
        self.repo_root = Path(repo_root)
        self.blocks_dir = self.repo_root / "blocks"
        self.layers_dir = self.repo_root / "layers"
        self.manifests_dir = self.repo_root / "manifests"
        self.index = {}  # Tracks stored blocks {hash: path}

        # Create directories
        self.blocks_dir.mkdir(parents=True, exist_ok=True)
        self.layers_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def _chunk_file(self, file_path, chunk_size=4096):
        """Split file into fixed-size chunks (4KB default)"""
        with open(file_path, "rb") as f:
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

    def store_layer(self, layer_path, layer_digest):
        """Process and store a Docker layer"""
        layer_dir = self.layers_dir / layer_digest
        if layer_dir.exists():  # Layer already exists
            return layer_digest

        layer_dir.mkdir()
        recipe = {"chunks": []}

        # Process layer in chunks
        for chunk in self._chunk_file(layer_path):
            chunk_hash = self.store_block(chunk)
            recipe["chunks"].append(chunk_hash)

        # Save layer metadata
        (layer_dir / "recipe.json").write_text(json.dumps(recipe))
        return layer_digest

    def store_manifest(self, manifest_data, image_name):
        """Store image manifest and process layers"""
        manifest = json.loads(manifest_data)
        manifest_digest = "sha256:" + hashlib.sha256(manifest_data).hexdigest()
        
        # Save manifest
        manifest_path = self.manifests_dir / image_name / manifest_digest
        manifest_path.parent.mkdir(exist_ok=True)
        manifest_path.write_text(manifest_data)

        # Process layers
        for layer in manifest.get("layers", []):
            layer_file = self.repo_root / "uploads" / layer["digest"].replace("sha256:", "")
            if layer_file.exists():
                self.store_layer(layer_file, layer["digest"])

        return manifest_digest

    def layer_exists(self, layer_digest):
        """Check if layer is already stored"""
        return (self.layers_dir / layer_digest).exists()

    def get_manifest(self, image_name, reference):
        """Retrieve stored manifest"""
        manifest_path = self.manifests_dir / image_name / reference
        if manifest_path.exists():
            return manifest_path.read_text()
        return None
