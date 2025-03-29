from flask import Flask, request, Response, make_response
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

@app.route('/v2/<image_name>/blobs/uploads/<upload_id>', methods=['PATCH', 'PUT'])
def handle_upload(image_name, upload_id):
    upload_path = storage.repo_root / "uploads" / upload_id
    
    # Write the incoming data
    with open(upload_path, 'ab') as f:
        data = request.get_data()
        f.write(data)
    
    # Handle PUT (finalize)
    if request.method == 'PUT':
        digest = request.args.get('digest')
        if not digest:
            return make_response(
                json.dumps({'errors': [{'code': 'DIGEST_INVALID'}]}),
                400,
                {'Content-Type': 'application/json'}
            )
        
        # Verify digest
        with open(upload_path, 'rb') as f:
            file_data = f.read()
            computed_digest = 'sha256:' + hashlib.sha256(file_data).hexdigest()
            if computed_digest != digest:
                return make_response(
                    json.dumps({'errors': [{'code': 'DIGEST_INVALID'}]}),
                    400,
                    {'Content-Type': 'application/json'}
                )
        
        # Store layer
        try:
            stored_digest = storage.store_layer(upload_path, digest)
            os.remove(upload_path)
            return Response(
                status=201,
                headers={
                    'Docker-Content-Digest': stored_digest,
                    'Content-Length': '0'
                }
            )
        except Exception as e:
            return make_response(
                json.dumps({'errors': [{'code': 'UNKNOWN', 'message': str(e)}]}),
                500,
                {'Content-Type': 'application/json'}
            )
    
    # For PATCH requests
    file_size = os.path.getsize(upload_path)
    return Response(
        status=202,
        headers={
            'Location': f'/v2/{image_name}/blobs/uploads/{upload_id}',
            'Range': f'0-{file_size-1}',
            'Content-Length': '0',
            'Docker-Upload-UUID': upload_id
        }
    )

@app.route('/v2/<image_name>/manifests/<reference>', methods=['PUT'])
def put_manifest(image_name, reference):
    try:
        manifest_data = request.get_data()
        content_type = request.headers.get('Content-Type')
        
        # Store manifest
        manifest_digest = storage.store_manifest(manifest_data, image_name)
        
        return Response(
            response=manifest_data,
            status=201,
            headers={
                'Docker-Content-Digest': manifest_digest,
                'Content-Type': content_type,
                'Content-Length': str(len(manifest_data))
            }
        )
    except Exception as e:
        return make_response(
            json.dumps({'errors': [{'code': 'UNKNOWN', 'message': str(e)}]}),
            500,
            {'Content-Type': 'application/json'}
        )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
