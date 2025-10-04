import { Search, Filter, Telescope, ChevronLeft } from "lucide-react";
import { motion } from "framer-motion";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { ViewState, Mission } from "../types/graph";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "./ui/popover";
import { Checkbox } from "./ui/checkbox";
import { Label } from "./ui/label";
import { Slider } from "./ui/slider";

interface ToolbarProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  filters: {
    yearRange: [number, number];
    missions: Mission[];
    showGaps: boolean;
  };
  onFiltersChange: (filters: any) => void;
  viewState: ViewState;
  onBackToUniverse: () => void;
  onBackToCluster: () => void;
  selectedClusterLabel?: string;
  selectedPaperLabel?: string;
}

export const Toolbar = ({
  searchQuery,
  onSearchChange,
  filters,
  onFiltersChange,
  viewState,
  onBackToUniverse,
  onBackToCluster,
  selectedClusterLabel,
  selectedPaperLabel,
}: ToolbarProps) => {
  const toggleMission = (mission: Mission) => {
    const newMissions = filters.missions.includes(mission)
      ? filters.missions.filter((m) => m !== mission)
      : [...filters.missions, mission];
    onFiltersChange({ ...filters, missions: newMissions });
  };

  return (
    <motion.div
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="border-b border-border bg-card/50 backdrop-blur-sm p-4"
    >
      <div className="flex items-center gap-4">
        {/* Breadcrumb Navigation */}
        <div className="flex items-center gap-2">
          {viewState.level !== "universe" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={viewState.level === "topic" ? onBackToCluster : onBackToUniverse}
              className="gap-1"
            >
              <ChevronLeft className="h-4 w-4" />
              Back
            </Button>
          )}
          
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Telescope className="h-4 w-4 text-primary" />
            <div className="font-medium">
              {viewState.level === "universe" && (
                <span>Knowledge Universe</span>
              )}
              {viewState.level === "cluster" && (
                <span>Cluster: <span className="text-foreground font-semibold">{selectedClusterLabel}</span></span>
              )}
              {viewState.level === "topic" && (
                <span>Paper: <span className="text-foreground font-semibold">{selectedPaperLabel}</span></span>
              )}
            </div>
          </div>
        </div>

        {/* Search (hidden in PaperDetails) */}
        {viewState.level !== "topic" && (
          <div className="flex-1 max-w-md relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search topics, papers, keywords..."
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-10 bg-background/50 border-border"
            />
          </div>
        )}

        {/* Filters Popover (hidden in PaperDetails) */}
        {viewState.level !== "topic" && (
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="gap-2">
                <Filter className="h-4 w-4" />
                Filters
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 bg-card border-border">
              <div className="space-y-4">
                <h4 className="font-medium text-sm">Filter Options</h4>
                
                <div className="space-y-2">
                  <Label className="text-sm font-medium">Missions</Label>
                  <div className="space-y-2">
                    {(["ISS", "Mars", "Moon"] as Mission[]).map((mission) => (
                      <div key={mission} className="flex items-center gap-2">
                        <Checkbox
                          id={mission}
                          checked={filters.missions.includes(mission)}
                          onCheckedChange={() => toggleMission(mission)}
                        />
                        <label
                          htmlFor={mission}
                          className="text-sm cursor-pointer"
                        >
                          {mission}
                        </label>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="space-y-2 pt-2 border-t border-border">
                  <Label className="text-sm font-medium">Year range</Label>
                  <div className="px-1">
                    <Slider
                      value={[filters.yearRange[0], filters.yearRange[1]]}
                      min={2000}
                      max={2025}
                      step={1}
                      onValueChange={(vals) => {
                        const [min, max] = vals as number[];
                        onFiltersChange({ ...filters, yearRange: [min, max] });
                      }}
                    />
                    <div className="flex justify-between text-xs text-muted-foreground mt-1">
                      <span>{filters.yearRange[0]}</span>
                      <span>{filters.yearRange[1]}</span>
                    </div>
                  </div>
                </div>

                <div className="space-y-2 pt-2 border-t border-border">
                  <Label className="text-sm font-medium">Sizing</Label>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="showGaps"
                      checked={filters.showGaps}
                      onCheckedChange={() => onFiltersChange({ ...filters, showGaps: !filters.showGaps })}
                    />
                    <label htmlFor="showGaps" className="text-sm cursor-pointer">
                      Scale node size by research gap
                    </label>
                  </div>
                </div>
              </div>
            </PopoverContent>
          </Popover>
        )}
        {/* Removed Gap Detection and Add Idea as requested */}
      </div>
    </motion.div>
  );
};
