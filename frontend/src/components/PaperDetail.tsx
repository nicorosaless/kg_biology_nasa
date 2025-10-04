import { motion } from "framer-motion";
import type { Paper } from "../types/graph";
import { TopicGraph } from "./TopicGraph";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";

export const PaperDetail = ({ paper }: { paper: Paper }) => {
  return (
    <div className="flex h-full w-full flex-col md:flex-row">
      {/* Left: PDF 45% */}
      <div className="w-full md:w-[45%] h-[45vh] md:h-full border-b md:border-b-0 md:border-r border-border bg-card">
        <div className="h-12 flex items-center px-3 border-b border-border">
          <h3 className="text-sm font-medium">PDF Preview</h3>
        </div>
        <div className="h-[calc(100%-3rem)]">
          <object
            data="https://mozilla.github.io/pdf.js/web/compressed.tracemonkey-pldi-09.pdf"
            type="application/pdf"
            className="w-full h-full"
          >
            <div className="p-4 text-sm text-muted-foreground">
              PDF preview not supported in this browser. <a className="underline" href="https://mozilla.github.io/pdf.js/web/compressed.tracemonkey-pldi-09.pdf" target="_blank" rel="noreferrer">Open PDF</a>.
            </div>
          </object>
        </div>
      </div>

      {/* Right: Tabs 55% */}
      <div className="w-full md:w-[55%] h-full bg-background">
        <Tabs defaultValue="summary" className="h-full w-full flex flex-col">
          <div className="h-12 flex items-center justify-between px-3 border-b border-border">
            <TabsList>
              <TabsTrigger value="summary">Summary</TabsTrigger>
              <TabsTrigger value="topics">Topics</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="summary" className="flex-1 overflow-auto p-4">
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
              <h2 className="text-lg font-semibold">{paper.label}</h2>
              <p className="text-sm text-muted-foreground">{paper.year} • Mission: {paper.mission} • Gap Score: {paper.gapScore}</p>
              <p className="text-sm leading-relaxed">{paper.summary}</p>
            </motion.div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-border bg-card p-3">
                <div className="text-xs text-muted-foreground">Citations (mock)</div>
                <div className="mt-2 text-2xl font-semibold">{Math.floor(20 + paper.gapScore * 100)}</div>
              </div>
              <div className="rounded-lg border border-border bg-card p-3">
                <div className="text-xs text-muted-foreground">Relevance (mock)</div>
                <div className="mt-2 h-2 w-full bg-muted rounded">
                  <div className="h-2 rounded bg-primary" style={{ width: `${70 + Math.round((1 - paper.gapScore) * 20)}%` }} />
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card p-3">
                <div className="text-xs text-muted-foreground">Read time (est.)</div>
                <div className="mt-2 text-2xl font-semibold">{12 + (paper.summary.length % 8)} min</div>
              </div>
              <div className="rounded-lg border border-border bg-card p-3">
                <div className="text-xs text-muted-foreground">Topics</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {paper.topics.map((t: string) => (
                    <span key={t} className="text-xs px-2 py-1 rounded-full bg-primary/10 text-primary border border-primary/20">{t}</span>
                  ))}
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="topics" className="flex-1 p-0">
            <div className="h-[calc(100vh-3rem-3rem)] md:h-[calc(100vh-3rem)]">
              <TopicGraph paper={paper} />
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
};
