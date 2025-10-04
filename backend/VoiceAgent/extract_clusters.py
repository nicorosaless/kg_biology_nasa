import json

unique_clusters = set()

with open('kb_publications.txt', 'r') as f:
    for line in f:
        data = json.loads(line.strip())
        unique_clusters.add(data['clusterLabel'])

with open('macroclusters.txt', 'w') as f:
    for cluster in sorted(unique_clusters):
        f.write(cluster + '\n')