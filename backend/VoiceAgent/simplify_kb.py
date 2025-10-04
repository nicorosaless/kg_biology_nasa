import json

with open('kb_publications.txt', 'r') as f_in, open('kb_publications_simplified.txt', 'w') as f_out:
    for line in f_in:
        data = json.loads(line.strip())
        simplified = {
            "title": data["title"],
            "clusterLabel": data["clusterLabel"]
        }
        f_out.write(json.dumps(simplified) + '\n')