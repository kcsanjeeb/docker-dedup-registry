# Pure Block-Level Storage 

Based on implementation and the observed behavior, here's the analysis of block reuse and storage patterns:

### Initial Storage Analysis:
* After pushing nginx-v2, storage grew from 129MB to 199MB (+70MB) and blocks from 16,159 to 25,002 (+8,843)
* Pushing nginx-v3 grew storage to 348MB (+149MB) and blocks to 43,897 (+18,895)

### Block Reuse Observations:
* Between v1 and v2 (same base image):
    * `375990b2a90a: Layer already exists`

### v3 Storage Impact:
* The 149MB growth for v3 comes from:
    * Different base image (Ubuntu 20.04 vs latest)
    * Different nginx package versions in apt repositories
    * New layer checksums due to different timestamps or package contents

## Steps 

### After first push `localhost:5001/nginx-v2`
```shell
[root@hssl block-storage]# du -sh data/
129M	data/
[root@hssl block-storage]# ls data/blocks | wc -l 
16159
```

### After second push `localhost:5001/nginx-v2`
```shell
[root@hssl block-storage]# docker push localhost:5001/nginx-v2
Using default tag: latest
The push refers to repository [localhost:5001/nginx-v2]
5eec801e71a8: Pushed 
375990b2a90a: Layer already exists 
latest: digest: sha256:1772efe5fde950babb153ecc19df03b98e78c714663c3735abf68707d27b26b8 size: 741

[root@hssl block-storage]# du -sh data/
199M	data/
[root@hssl block-storage]# ls data/blocks | wc -l 
25002
```

### After third push `localhost:5001/nginx-v2`
```shell
[root@hssl block-storage]# docker push localhost:5001/nginx-v3 
Using default tag: latest
The push refers to repository [localhost:5001/nginx-v3]
e4a147a41563: Pushed 
171652ecd561: Pushed 
latest: digest: sha256:b6027ddd0473be05e7d5045f7b4cc009a9ee768ed27221673010dfbb2456ba72 size: 741

[root@hssl block-storage]# du -sh data/
348M	data/
[root@hssl block-storage]# ls data/blocks | wc -l 
43897
```

---

## In Case of Traditional Docker Registry (Layer-Based)

```shell
[root@hssl ~]# docker ps 
CONTAINER ID   IMAGE        COMMAND                  CREATED          STATUS          PORTS                                         NAMES
73606cc60840   registry:2   "/entrypoint.sh /etc…"   41 seconds ago   Up 40 seconds   0.0.0.0:5000->5000/tcp, [::]:5000->5000/tcp   traditional-registry

[root@hssl ~]# docker tag nginx-v1 localhost:5000/nginx-v1 
[root@hssl ~]# docker tag nginx-v2 localhost:5000/nginx-v2
[root@hssl ~]# docker tag nginx-v3 localhost:5000/nginx-v3

# ---------------------- localhost:5000/nginx-v1 ----------------------
[root@hssl ~]# docker push localhost:5000/nginx-v1
Using default tag: latest
The push refers to repository [localhost:5000/nginx-v1]
09be7864001e: Pushed 
375990b2a90a: Pushed 
latest: digest: sha256:1a4aa86d6b9a184dc0a7b622b22b57f840646735d345e156fd713f82b082f695 size: 741
[root@hssl ~]# docker exec traditional-registry du -sh /var/lib/registry
63.2M	/var/lib/registry


# ---------------------- localhost:5000/nginx-v2 ----------------------
[root@hssl ~]# docker push localhost:5001/nginx-v2
Using default tag: latest
The push refers to repository [localhost:5001/nginx-v2]
5eec801e71a8: Layer already exists 
375990b2a90a: Layer already exists 
latest: digest: sha256:1772efe5fde950babb153ecc19df03b98e78c714663c3735abf68707d27b26b8 size: 741
[root@hssl ~]# docker exec traditional-registry du -sh /var/lib/registry
63.2M	/var/lib/registry

# ---------------------- localhost:5000/nginx-v3 ----------------------
[root@hssl ~]# docker push localhost:5001/nginx-v3 
Using default tag: latest
The push refers to repository [localhost:5001/nginx-v3]
e4a147a41563: Layer already exists 
171652ecd561: Layer already exists 
latest: digest: sha256:b6027ddd0473be05e7d5045f7b4cc009a9ee768ed27221673010dfbb2456ba72 size: 741
[root@hssl ~]# docker exec traditional-registry du -sh /var/lib/registry
63.2M	/var/lib/registry

````

---

## Hey
* **Traditional:** 63.2MB (shared base layers)
* **Dedup Based:** 348MB (3× full layers + 43,897 chunks)