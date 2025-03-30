from flask import Flask, request, Response, make_response, jsonify, send_file
from storage_backend import DedupStorage
import os
import uuid
import hashlib
import json

app = Flask(__name__)
storage = DedupStorage()

@app.route('/v2/', methods=['GET'])
def v2_base():
    return Response(
        response='{}',
        headers={
            'Docker-Distribution-API-Version': 'registry/2.0',
            'Content-Type': 'application/json'
        }
    )


@app.route('/v2/<image_name>/blobs/uploads/', methods=['POST'])
def start_upload(image_name):
    upload_id = str(uuid.uuid4())
    upload_dir = storage.repo_root / "uploads"
    upload_dir.mkdir(exist_ok=True)
    (upload_dir / upload_id).touch()
    
    return Response(
        status=202,
        headers={
            'Location': f'/v2/{image_name}/blobs/uploads/{upload_id}',
            'Docker-Upload-UUID': upload_id,
            'Range': '0-0',
            'Content-Length': '0'
        }
    )

@app.route('/v2/<name>/blobs/uploads/<upload_id>', methods=['PUT'])
def put_upload(name, upload_id):
    try:
        digest = request.args.get('digest')
        if not digest or not digest.startswith('sha256:'):
            return jsonify({
                'errors': [{
                    'code': 'DIGEST_INVALID',
                    'message': 'Missing or invalid digest parameter'
                }]
            }), 400

        upload_path = storage.uploads_dir / upload_id
        if not upload_path.exists():
            return jsonify({
                'errors': [{
                    'code': 'BLOB_UPLOAD_UNKNOWN',
                    'message': 'Upload session not found'
                }]
            }), 404

        # Handle both cases: with and without request body
        temp_path = upload_path.with_suffix('.tmp')
        try:
            if request.content_length:
                # New content in PUT request
                with open(temp_path, 'wb') as f:
                    f.write(request.get_data())
            else:
                # Use existing uploaded content
                os.rename(upload_path, temp_path)

            # Store with verification
            stored_digest = storage.store_blob(temp_path, digest)
            
            return Response(
                status=201,
                headers={
                    'Docker-Content-Digest': stored_digest,
                    'Location': f'/v2/{name}/blobs/{stored_digest}',
                    'Content-Length': '0'
                }
            )
        except ValueError as e:
            return jsonify({
                'errors': [{
                    'code': 'DIGEST_INVALID',
                    'message': str(e)
                }]
            }), 400
        finally:
            if temp_path.exists():
                os.remove(temp_path)
            if upload_path.exists():
                os.remove(upload_path)
                
    except Exception as e:
        return jsonify({
            'errors': [{
                'code': 'INTERNAL_ERROR',
                'message': f"Blob upload failed: {str(e)}"
            }]
        }), 500

@app.route('/v2/<name>/blobs/uploads/<upload_id>', methods=['PATCH'])
def patch_upload(name, upload_id):
    try:
        upload_path = storage.uploads_dir / upload_id
        
        # Ensure upload directory exists
        storage.uploads_dir.mkdir(parents=True, exist_ok=True)
        
        # Create file if it doesn't exist
        if not upload_path.exists():
            upload_path.touch(mode=0o644)
        
        # Get current offset
        current_size = upload_path.stat().st_size
        
        # Append data
        with open(upload_path, 'ab') as f:
            f.write(request.get_data())
        
        new_size = upload_path.stat().st_size
        
        return Response(
            status=202,
            headers={
                'Location': f'/v2/{name}/blobs/uploads/{upload_id}',
                'Range': f'0-{new_size-1}',
                'Content-Length': '0',
                'Docker-Upload-UUID': upload_id
            }
        )
    except Exception as e:
        return jsonify({
            'errors': [{
                'code': 'BLOB_UPLOAD_UNKNOWN',
                'message': str(e)
            }]
        }), 500

@app.route('/v2/<name>/manifests/<reference>', methods=['PUT'])
def put_manifest(name, reference):
    try:
        manifest_data = request.get_data()
        
        # Validate manifest structure
        try:
            manifest = json.loads(manifest_data)
            if 'layers' not in manifest or 'config' not in manifest:
                raise ValueError("Invalid manifest structure")
        except (json.JSONDecodeError, ValueError) as e:
            return jsonify({
                'errors': [{
                    'code': 'MANIFEST_INVALID',
                    'message': str(e)
                }]
            }), 400

        # Verify all referenced blobs exist
        for layer in manifest['layers']:
            if not storage.blob_exists(layer['digest']):
                return jsonify({
                    'errors': [{
                        'code': 'BLOB_UNKNOWN',
                        'message': f"Layer {layer['digest']} not found"
                    }]
                }), 404
        
        if not storage.blob_exists(manifest['config']['digest']):
            return jsonify({
                'errors': [{
                    'code': 'BLOB_UNKNOWN',
                    'message': f"Config {manifest['config']['digest']} not found"
                }]
            }), 404

        # Store manifest
        manifest_digest = storage.store_manifest(name, reference, manifest_data)
        
        return Response(
            status=201,
            headers={
                'Docker-Content-Digest': manifest_digest,
                'Location': f'/v2/{name}/manifests/{reference}',
                'Content-Type': 'application/vnd.docker.distribution.manifest.v2+json'
            }
        )
    except Exception as e:
        return jsonify({
            'errors': [{
                'code': 'INTERNAL_ERROR',
                'message': str(e)
            }]
        }), 500
        
@app.route('/v2/<name>/manifests/<reference>', methods=['GET'])
def get_manifest(name, reference):
    manifest_path = storage.manifests_dir / name / reference
    if not manifest_path.exists():
        return jsonify({
            'errors': [{
                'code': 'MANIFEST_UNKNOWN',
                'message': f"Manifest {name}:{reference} not found"
            }]
        }), 404
    
    with open(manifest_path, 'rb') as f:
        manifest_data = f.read()
    
    return Response(
        manifest_data,
        mimetype='application/vnd.docker.distribution.manifest.v2+json',
        headers={
            'Docker-Content-Digest': 'sha256:' + hashlib.sha256(manifest_data).hexdigest()
        }
    )
    
@app.route('/v2/<name>/blobs/<digest>', methods=['GET'])
def get_blob(name, digest):
    """Reconstruct and serve blobs from deduplicated chunks"""
    if not digest.startswith('sha256:'):
        return jsonify({
            'errors': [{'code': 'DIGEST_INVALID', 'message': 'Invalid digest format'}]
        }), 400

    # Check if it's a config blob (small, stored whole)
    config_path = storage.layers_dir / digest.replace('sha256:', '') / "config"
    if config_path.exists():
        return send_file(
            config_path,
            mimetype='application/octet-stream',
            headers={'Docker-Content-Digest': digest}
        )

    # Handle layer blobs (reconstruct from chunks)
    recipe_path = storage.layers_dir / digest.replace('sha256:', '') / "recipe.json"
    if not recipe_path.exists():
        return jsonify({
            'errors': [{'code': 'BLOB_UNKNOWN', 'message': 'Blob not found'}]
        }), 404

    try:
        with open(recipe_path) as f:
            recipe = json.load(f)
        
        def generate():
            """Stream reconstructed layer from chunks"""
            for chunk_hash in recipe['chunks']:
                chunk_path = storage.blocks_dir / chunk_hash
                if not chunk_path.exists():
                    raise FileNotFoundError(f"Missing chunk {chunk_hash}")
                with open(chunk_path, 'rb') as f:
                    yield f.read()

        return Response(
            generate(),
            mimetype='application/octet-stream',
            headers={'Docker-Content-Digest': digest}
        )
    except Exception as e:
        return jsonify({
            'errors': [{
                'code': 'BLOB_UNKNOWN',
                'message': f'Reconstruction failed: {str(e)}'
            }]
        }), 404

@app.route('/v2/<name>/blobs/<digest>', methods=['HEAD'])
def head_blob(name, digest):
    """Return blob metadata without content"""
    if not digest.startswith('sha256:'):
        return jsonify({
            'errors': [{'code': 'DIGEST_INVALID', 'message': 'Invalid digest format'}]
        }), 400

    # Handle config blobs
    config_path = storage.layers_dir / digest.replace('sha256:', '') / "config"
    if config_path.exists():
        return Response(headers={
            'Docker-Content-Digest': digest,
            'Content-Length': str(config_path.stat().st_size)
        })

    # Handle layer blobs
    recipe_path = storage.layers_dir / digest.replace('sha256:', '') / "recipe.json"
    if not recipe_path.exists():
        return jsonify({
            'errors': [{'code': 'BLOB_UNKNOWN', 'message': 'Blob not found'}]
        }), 404

    try:
        with open(recipe_path) as f:
            recipe = json.load(f)
        
        # Calculate total size from chunks
        total_size = 0
        for chunk_hash in recipe['chunks']:
            chunk_path = storage.blocks_dir / chunk_hash
            if not chunk_path.exists():
                raise FileNotFoundError(f"Missing chunk {chunk_hash}")
            total_size += chunk_path.stat().st_size

        return Response(headers={
            'Docker-Content-Digest': digest,
            'Content-Length': str(total_size)
        })
    except Exception as e:
        return jsonify({
            'errors': [{
                'code': 'BLOB_UNKNOWN', 
                'message': f'Size calculation failed: {str(e)}'
            }]
        }), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
