export type Mission = "ISS" | "Mars" | "Moon";

export interface Cluster {
  id: string;
  label: string;
  count: number;
  mission: Mission;
  description: string;
}

export interface Paper {
  id: string;
  clusterId: string;
  label: string;
  topics: string[];
  year: number;
  mission: Mission;
  gapScore: number;
  summary: string;
}

export interface Edge {
  source: string;
  target: string;
  weight: number;
}

export interface GraphData {
  clusters: Cluster[];
  papers: Paper[];
  edges: Edge[];
}

export type ViewLevel = "universe" | "cluster" | "topic";

export interface ViewState {
  level: ViewLevel;
  selectedClusterId?: string;
  selectedPaperId?: string;
}
