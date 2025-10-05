import json
import random
from collections import defaultdict

# Read the current graph data
with open('/Users/alexlatorre/Downloads/kg_biology_nasa/frontend/public/data/csvGraph.json', 'r') as f:
    graph_data = json.load(f)

papers = graph_data['papers']
clusters = graph_data['clusters']

# Create a mapping of papers by cluster
papers_by_cluster = defaultdict(list)
for paper in papers:
    papers_by_cluster[paper['clusterId']].append(paper['id'])

# Get all paper IDs
all_paper_ids = [p['id'] for p in papers]

def calculate_weight(paper1, paper2):
    """Calculate edge weight based on some criteria"""
    # For simplicity, we'll use random weights between 0.3 and 0.9
    return round(random.uniform(0.3, 0.9), 2)

def generate_edges():
    """Generate edges with varied connections (2-6 per node)"""
    edges = []
    edge_set = set()  # To avoid duplicate edges
    node_connections = defaultdict(int)  # Track connections per node
    
    # First pass: Create intra-cluster connections
    for cluster_id, paper_ids in papers_by_cluster.items():
        if len(paper_ids) < 2:
            continue
            
        # For each paper in the cluster, connect to 1-3 other papers in same cluster
        for paper_id in paper_ids:
            # Determine how many connections this paper should have within cluster
            num_intra_cluster = random.randint(1, min(3, len(paper_ids) - 1))
            
            # Get potential targets (excluding self)
            potential_targets = [p for p in paper_ids if p != paper_id]
            
            # Select random targets
            targets = random.sample(potential_targets, min(num_intra_cluster, len(potential_targets)))
            
            for target in targets:
                # Create edge (ensure alphabetical order to avoid duplicates)
                edge_tuple = tuple(sorted([paper_id, target]))
                
                if edge_tuple not in edge_set and node_connections[paper_id] < 6 and node_connections[target] < 6:
                    edge_set.add(edge_tuple)
                    weight = calculate_weight(paper_id, target)
                    edges.append({
                        "source": edge_tuple[0],
                        "target": edge_tuple[1],
                        "weight": weight
                    })
                    node_connections[paper_id] += 1
                    node_connections[target] += 1
    
    # Second pass: Create inter-cluster connections for diversity
    cluster_ids = list(papers_by_cluster.keys())
    
    for cluster_id in cluster_ids:
        paper_ids = papers_by_cluster[cluster_id]
        
        # Select a few papers from this cluster to connect to other clusters
        num_cross_cluster = min(len(paper_ids), random.randint(2, 5))
        selected_papers = random.sample(paper_ids, num_cross_cluster)
        
        for paper_id in selected_papers:
            # Don't add cross-cluster edges if already at max connections
            if node_connections[paper_id] >= 6:
                continue
                
            # Select 1-2 random other clusters
            other_clusters = [c for c in cluster_ids if c != cluster_id]
            num_target_clusters = random.randint(1, min(2, len(other_clusters)))
            target_clusters = random.sample(other_clusters, num_target_clusters)
            
            for target_cluster in target_clusters:
                # Select a random paper from target cluster
                target_papers = papers_by_cluster[target_cluster]
                if not target_papers:
                    continue
                    
                target_paper = random.choice(target_papers)
                
                # Check if target isn't already maxed out
                if node_connections[target_paper] >= 6:
                    continue
                
                # Create edge
                edge_tuple = tuple(sorted([paper_id, target_paper]))
                
                if edge_tuple not in edge_set:
                    edge_set.add(edge_tuple)
                    weight = calculate_weight(paper_id, target_paper)
                    edges.append({
                        "source": edge_tuple[0],
                        "target": edge_tuple[1],
                        "weight": weight
                    })
                    node_connections[paper_id] += 1
                    node_connections[target_paper] += 1
                    
                    # Stop if we've reached max connections
                    if node_connections[paper_id] >= 6:
                        break
    
    # Third pass: Ensure minimum connections for isolated nodes
    for paper_id in all_paper_ids:
        if node_connections[paper_id] < 2:
            # This node needs more connections
            needed = 2 - node_connections[paper_id]
            
            # Try to connect to papers in the same cluster first
            cluster_id = next((p['clusterId'] for p in papers if p['id'] == paper_id), None)
            potential_targets = [p for p in papers_by_cluster.get(cluster_id, []) if p != paper_id]
            
            # If not enough in same cluster, expand to all papers
            if len(potential_targets) < needed:
                potential_targets = [p for p in all_paper_ids if p != paper_id]
            
            # Filter out already connected nodes and maxed out nodes
            existing_connections = set()
            for edge in edges:
                if edge['source'] == paper_id:
                    existing_connections.add(edge['target'])
                elif edge['target'] == paper_id:
                    existing_connections.add(edge['source'])
            
            potential_targets = [
                p for p in potential_targets 
                if p not in existing_connections and node_connections[p] < 6
            ]
            
            if potential_targets:
                num_to_add = min(needed, len(potential_targets))
                new_targets = random.sample(potential_targets, num_to_add)
                
                for target in new_targets:
                    edge_tuple = tuple(sorted([paper_id, target]))
                    if edge_tuple not in edge_set:
                        edge_set.add(edge_tuple)
                        weight = calculate_weight(paper_id, target)
                        edges.append({
                            "source": edge_tuple[0],
                            "target": edge_tuple[1],
                            "weight": weight
                        })
                        node_connections[paper_id] += 1
                        node_connections[target] += 1
    
    return edges, node_connections

# Generate new edges
print("Generating new edges...")
new_edges, node_connections = generate_edges()

# Print statistics
print(f"\nGenerated {len(new_edges)} edges")
print(f"Nodes: {len(all_paper_ids)}")
print(f"Average edges per node: {len(new_edges) * 2 / len(all_paper_ids):.2f}")

connection_counts = defaultdict(int)
for count in node_connections.values():
    connection_counts[count] += 1

print("\nConnection distribution:")
for i in range(0, 7):
    print(f"  Nodes with {i} connections: {connection_counts[i]}")

# Update graph data
graph_data['edges'] = new_edges

# Save to file
print("\nSaving updated graph...")
with open('/Users/alexlatorre/Downloads/kg_biology_nasa/frontend/public/data/csvGraph.json', 'w') as f:
    json.dump(graph_data, f, indent=2)

print("Done! Graph edges have been regenerated.")
