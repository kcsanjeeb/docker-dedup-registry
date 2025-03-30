from flask import Flask, request, Response, make_response, jsonify, send_file
from storage_backend import DedupStorage
import os
import uuid
import hashlib
import json

app = Flask(__name__)
storage = DedupStorage()

@app.after_request
def add_required_headers(response):
    """Ensure all responses have required headers"""
    if request.path.startswith('/v2/'):
        # Ensure Content-Type for all responses
        if 'Content-Type' not in response.headers:
            response.headers['Content-Type'] = 'application/json'
        
        # Ensure Content-Length for successful responses
        if response.status_code in (200, 201) and 'Content-Length' not in response.headers:
            if response.data:
                response.headers['Content-Length'] = str(len(response.data))
            else:
                response.headers['Content-Length'] = '0'
    
    return response

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

        temp_path = upload_path.with_suffix('.tmp')
        try:
            if request.content_length:
                with open(temp_path, 'wb') as f:
                    f.write(request.get_data())
            else:
                os.rename(upload_path, temp_path)

            stored_digest = storage.store_blob(temp_path, digest)
            
            return Response(
                status=201,
                headers={
                    'Docker-Content-Digest': stored_digest,
                    'Location': f'/v2/{name}/blobs/{stored_digest}',
                    'Content-Length': '0',
                    'Content-Type': 'application/octet-stream'
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
        
        if not upload_path.exists():
            return jsonify({
                'errors': [{
                    'code': 'BLOB_UPLOAD_UNKNOWN',
                    'message': 'Upload session not found'
                }]
            }), 404

        # Get current size before writing
        current_size = upload_path.stat().st_size
        
        # Append data
        with open(upload_path, 'ab') as f:
            data = request.get_data()
            if not data:
                return jsonify({
                    'errors': [{
                        'code': 'BLOB_UPLOAD_INVALID',
                        'message': 'Empty content'
                    }]
                }), 400
            f.write(data)
        
        new_size = upload_path.stat().st_size
        
        return Response(
            status=202,
            headers={
                'Location': f'/v2/{name}/blobs/uploads/{upload_id}',
                'Range': f'0-{new_size-1}',
                'Content-Length': '0',
                'Docker-Upload-UUID': upload_id,
                'Content-Type': 'application/octet-stream'
            }
        )
    except Exception as e:
        return jsonify({
            'errors': [{
                'code': 'BLOB_UPLOAD_UNKNOWN',
                'message': str(e)
            }]
        }), 500

@app.route('/v2/<name>/blobs/uploads/<upload_id>', methods=['DELETE'])
def delete_upload(name, upload_id):
    upload_path = storage.uploads_dir / upload_id
    if upload_path.exists():
        upload_path.unlink()
    return Response(status=204)

@app.route('/v2/<name>/manifests/<reference>', methods=['PUT'])
def put_manifest(name, reference):
    try:
        # Verify content type
        if request.headers.get('Content-Type') not in [
            'application/vnd.docker.distribution.manifest.v2+json',
            'application/vnd.oci.image.manifest.v1+json'
        ]:
            return jsonify({
                'errors': [{
                    'code': 'MANIFEST_INVALID',
                    'message': 'Unsupported content type'
                }]
            }), 400

        manifest_data = request.get_data()
        
        # Parse and validate manifest
        try:
            manifest = json.loads(manifest_data)
            if not all(k in manifest for k in ['schemaVersion', 'layers', 'config']):
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
                        'message': f"Missing layer: {layer['digest']}"
                    }]
                }), 404

        if not storage.blob_exists(manifest['config']['digest']):
            return jsonify({
                'errors': [{
                    'code': 'BLOB_UNKNOWN',
                    'message': f"Missing config: {manifest['config']['digest']}"
                }]
            }), 404

        # Store manifest
        manifest_dir = storage.manifests_dir / name
        manifest_dir.mkdir(parents=True, exist_ok=True)
        
        # Store by both tag and digest
        manifest_digest = 'sha256:' + hashlib.sha256(manifest_data).hexdigest()
        (manifest_dir / reference).write_bytes(manifest_data)
        (manifest_dir / manifest_digest).write_bytes(manifest_data)
        
        return Response(
            status=201,
            headers={
                'Docker-Content-Digest': manifest_digest,
                'Location': f'/v2/{name}/manifests/{reference}',
                'Content-Type': request.headers['Content-Type']
            }
        )
    except Exception as e:
        return jsonify({
            'errors': [{
                'code': 'INTERNAL_ERROR',
                'message': f"Manifest storage failed: {str(e)}"
            }]
        }), 500
      
@app.route('/v2/<name>/manifests/<reference>', methods=['GET'])
def get_manifest(name, reference):
    manifest_path = storage.manifests_dir / name / reference
    if not manifest_path.exists():
        return jsonify({
            'errors': [{'code': 'MANIFEST_UNKNOWN'}]
        }), 404
        
    with open(manifest_path, 'rb') as f:
        content = f.read()
        digest = 'sha256:' + hashlib.sha256(content).hexdigest()
        
    return Response(
        content,
        mimetype='application/vnd.docker.distribution.manifest.v2+json',
        headers={
            'Docker-Content-Digest': digest,
            'Content-Length': str(len(content))
        }
    )
    
@app.route('/v2/<name>/blobs/<digest>', methods=['GET'])
def get_blob(name, digest):
    """Serve blobs with proper headers"""
    if not digest.startswith('sha256:'):
        return jsonify({
            'errors': [{'code': 'DIGEST_INVALID', 'message': 'Invalid digest format'}]
        }), 400

    # Check config blobs first
    config_path = storage.layers_dir / digest.replace('sha256:', '') / "config"
    if config_path.exists():
        response = send_file(
            config_path,
            mimetype='application/octet-stream'
        )
        response.headers['Docker-Content-Digest'] = digest
        response.headers['Content-Length'] = str(config_path.stat().st_size)
        return response

    # Check full data blobs
    data_path = storage.layers_dir / digest.replace('sha256:', '') / "data"
    if data_path.exists():
        response = send_file(
            data_path,
            mimetype='application/octet-stream'
        )
        response.headers['Docker-Content-Digest'] = digest
        response.headers['Content-Length'] = str(data_path.stat().st_size)
        return response

    # Handle recipe-based blobs
    recipe_path = storage.layers_dir / digest.replace('sha256:', '') / "recipe.json"
    if recipe_path.exists():
        try:
            with open(recipe_path) as f:
                recipe = json.load(f)
            
            # Calculate total size first
            total_size = 0
            for chunk_hash in recipe['chunks']:
                chunk_path = storage.blocks_dir / chunk_hash
                if not chunk_path.exists():
                    raise FileNotFoundError(f"Missing chunk {chunk_hash}")
                total_size += chunk_path.stat().st_size

            def generate():
                """Stream reconstructed layer from chunks"""
                for chunk_hash in recipe['chunks']:
                    chunk_path = storage.blocks_dir / chunk_hash
                    with open(chunk_path, 'rb') as f:
                        yield f.read()

            response = Response(
                generate(),
                mimetype='application/octet-stream'
            )
            response.headers['Docker-Content-Digest'] = digest
            response.headers['Content-Length'] = str(total_size)
            return response
        except Exception as e:
            return jsonify({
                'errors': [{
                    'code': 'BLOB_UNKNOWN',
                    'message': f'Reconstruction failed: {str(e)}'
                }]
            }), 404

    return jsonify({
        'errors': [{'code': 'BLOB_UNKNOWN', 'message': 'Blob not found'}]
    }), 404
      
@app.route('/v2/<name>/blobs/<digest>', methods=['HEAD'])
def head_blob(name, digest):
    """Return blob metadata with proper headers"""
    if not digest.startswith('sha256:'):
        return jsonify({
            'errors': [{'code': 'DIGEST_INVALID', 'message': 'Invalid digest format'}]
        }), 400

    blob_id = digest.replace('sha256:', '')
    headers = {
        'Docker-Content-Digest': digest,
        'Content-Type': 'application/octet-stream'
    }

    try:
        # Check config blobs
        config_path = storage.layers_dir / blob_id / "config"
        if config_path.exists():
            headers['Content-Length'] = str(config_path.stat().st_size)
            return Response(headers=headers)

        # Check full data blobs
        data_path = storage.layers_dir / blob_id / "data"
        if data_path.exists():
            headers['Content-Length'] = str(data_path.stat().st_size)
            return Response(headers=headers)

        # Check recipe-based blobs
        recipe_path = storage.layers_dir / blob_id / "recipe.json"
        if recipe_path.exists():
            with open(recipe_path) as f:
                recipe = json.load(f)
            total_size = sum(
                (storage.blocks_dir / chunk_hash).stat().st_size
                for chunk_hash in recipe['chunks']
                if (storage.blocks_dir / chunk_hash).exists()
            )
            headers['Content-Length'] = str(total_size)
            return Response(headers=headers)

        # Check direct blocks
        block_path = storage.blocks_dir / blob_id
        if block_path.exists():
            headers['Content-Length'] = str(block_path.stat().st_size)
            return Response(headers=headers)

    except Exception as e:
        app.logger.error(f"Error in HEAD blob: {str(e)}")
        return jsonify({
            'errors': [{
                'code': 'INTERNAL_ERROR',
                'message': 'Internal server error'
            }]
        }), 500

    return jsonify({
        'errors': [{'code': 'BLOB_UNKNOWN', 'message': 'Blob not found'}]
    }), 404

@app.errorhandler(500)
def handle_internal_error(e):
    """Handle 500 errors gracefully"""
    app.logger.error(f"Internal server error: {str(e)}")
    return jsonify({
        'errors': [{
            'code': 'INTERNAL_ERROR',
            'message': 'Internal server error'
        }]
    }), 500
     
@app.route('/debug/storage', methods=['GET'])
def debug_storage():
    """Debug endpoint to verify storage"""
    stats = {
        'blocks_count': len(list(storage.blocks_dir.glob('*'))),
        'layers_count': len(list(storage.layers_dir.glob('*'))),
        'index_size': len(storage.index),
        'sample_block': next((f.name for f in storage.blocks_dir.iterdir()), None),
        'sample_layer': next((f.name for f in storage.layers_dir.iterdir()), None)
    }
    return jsonify(stats)

@app.route('/debug/verify', methods=['GET'])
def debug_verify():
    """Verify storage integrity"""
    try:
        valid, errors = storage.verify_storage()
        return jsonify({
            "valid": valid,
            "errors": errors,
            "blocks_count": len(list(storage.blocks_dir.glob('*')))
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
