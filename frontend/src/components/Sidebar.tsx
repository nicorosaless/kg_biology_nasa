import { motion } from "framer-motion";
import { ViewState, Cluster, Paper, GraphData } from "../types/graph";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { MessageSquare, Calendar, Target, TrendingUp } from "lucide-react";
import { Separator } from "./ui/separator";

interface SidebarProps {
  viewState: ViewState;
  selectedCluster?: Cluster;
  selectedPaper?: Paper;
  graphData: GraphData;
}

export const Sidebar = ({
  viewState,
  selectedCluster,
  selectedPaper,
  graphData,
}: SidebarProps) => {
  const getMissionColor = (mission: string) => {
    switch (mission) {
      case "ISS":
        return "text-mission-iss";
      case "Mars":
        return "text-mission-mars";
      case "Moon":
        return "text-mission-moon";
      default:
        return "text-foreground";
    }
  };

  return (
    <motion.div
      initial={{ x: 20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="w-96 border-l border-border bg-card/30 backdrop-blur-sm overflow-y-auto"
    >
      <div className="p-6 space-y-6">
        {/* Header */}
        <div>
          <h2 className="text-2xl font-bold bg-gradient-cosmic bg-clip-text text-transparent">
            Talkable Scientist
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            NASA Space Apps Challenge 2024
          </p>
        </div>

        <Separator className="bg-border" />

        {/* Universe View Info */}
        {viewState.level === "universe" && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            <div>
              <h3 className="text-lg font-semibold mb-2">Knowledge Universe</h3>
              <p className="text-sm text-muted-foreground">
                Explore {graphData.clusters.length} research clusters representing{" "}
                {graphData.papers.length} bioscience publications from NASA missions.
              </p>
            </div>

            <Card className="p-4 bg-secondary/50 border-border">
              <h4 className="font-medium mb-3 text-sm">Dataset Statistics</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Total Papers:</span>
                  <span className="font-medium">{graphData.papers.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Research Areas:</span>
                  <span className="font-medium">{graphData.clusters.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Connections:</span>
                  <span className="font-medium">{graphData.edges.length}</span>
                </div>
              </div>
            </Card>

            <div>
              <h4 className="font-medium mb-2 text-sm">Mission Distribution</h4>
              <div className="flex gap-2 flex-wrap">
                <Badge variant="outline" className={getMissionColor("ISS")}>
                  ISS: {graphData.papers.filter((p) => p.mission === "ISS").length}
                </Badge>
                <Badge variant="outline" className={getMissionColor("Mars")}>
                  Mars: {graphData.papers.filter((p) => p.mission === "Mars").length}
                </Badge>
                <Badge variant="outline" className={getMissionColor("Moon")}>
                  Moon: {graphData.papers.filter((p) => p.mission === "Moon").length}
                </Badge>
              </div>
            </div>
          </motion.div>
        )}

        {/* Cluster View Info */}
        {viewState.level === "cluster" && selectedCluster && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            <div>
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-lg font-semibold">{selectedCluster.label}</h3>
                <Badge variant="outline" className={getMissionColor(selectedCluster.mission)}>
                  {selectedCluster.mission}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                {selectedCluster.description}
              </p>
            </div>

            <Card className="p-4 bg-secondary/50 border-border">
              <div className="space-y-3 text-sm">
                <div className="flex items-center gap-2">
                  <Target className="h-4 w-4 text-primary" />
                  <span className="font-medium">{selectedCluster.count} Publications</span>
                </div>
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-accent" />
                  <span className="text-muted-foreground">2000-2025</span>
                </div>
              </div>
            </Card>

            <div>
              <h4 className="font-medium mb-2 text-sm flex items-center gap-2">
                <TrendingUp className="h-4 w-4" />
                AI Insights
              </h4>
              <Card className="p-3 bg-primary/10 border-primary/20">
                <p className="text-xs text-foreground">
                  This cluster shows high research activity in the past 3 years with
                  emerging focus on long-duration spaceflight applications.
                </p>
              </Card>
            </div>
          </motion.div>
        )}

        {/* Paper View Info */}
        {viewState.level === "topic" && selectedPaper && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            <div>
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-lg font-semibold">{selectedPaper.label}</h3>
              </div>
              <div className="flex items-center gap-2 mb-3">
                <Badge variant="outline" className={getMissionColor(selectedPaper.mission)}>
                  {selectedPaper.mission}
                </Badge>
                <Badge variant="outline">
                  <Calendar className="h-3 w-3 mr-1" />
                  {selectedPaper.year}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                {selectedPaper.summary}
              </p>
            </div>

            <div>
              <h4 className="font-medium mb-2 text-sm">Key Topics</h4>
              <div className="flex gap-2 flex-wrap">
                {selectedPaper.topics.map((topic) => (
                  <Badge key={topic} variant="secondary">
                    {topic}
                  </Badge>
                ))}
              </div>
            </div>

            <Card className="p-4 bg-secondary/50 border-border">
              <h4 className="font-medium mb-2 text-sm">Research Gap Score</h4>
              <div className="flex items-center gap-3">
                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${selectedPaper.gapScore * 100}%` }}
                    className="h-full bg-gradient-cosmic"
                  />
                </div>
                <span className="text-sm font-medium">
                  {(selectedPaper.gapScore * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                {selectedPaper.gapScore > 0.5
                  ? "High potential for new research"
                  : "Well-studied area"}
              </p>
            </Card>
          </motion.div>
        )}

        <Separator className="bg-border" />

        {/* Talk to Scientist Button */}
        <Button className="w-full gap-2 bg-gradient-cosmic hover:opacity-90">
          <MessageSquare className="h-4 w-4" />
          Talk to Scientist
        </Button>
      </div>
    </motion.div>
  );
};
