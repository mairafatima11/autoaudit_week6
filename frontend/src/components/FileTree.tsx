import { useState } from "react";
import { ChevronRight, ChevronDown, File, Folder, FolderOpen } from "lucide-react";
import { cn } from "../lib/utils";
import type { FileTreeNode } from "../lib/types";

function fileHasFindings(path: string, findingFiles: Set<string>) {
  return findingFiles.has(path);
}

function TreeNode({
  node,
  depth,
  selectedPath,
  onSelect,
  findingFiles,
  defaultOpen,
}: {
  node: FileTreeNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  findingFiles: Set<string>;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  if (node.type === "file") {
    const hasFindings = fileHasFindings(node.path, findingFiles);
    const isSelected = selectedPath === node.path;
    return (
      <button
        onClick={() => onSelect(node.path)}
        style={{ paddingLeft: depth * 14 + 10 }}
        className={cn(
          "flex w-full items-center gap-1.5 rounded py-1 pr-2 text-left text-[13px] transition-colors",
          isSelected ? "bg-signal/15 text-signal-glow" : "text-fog-1 hover:bg-panel-raised hover:text-fog-0"
        )}
      >
        <File size={13} className="shrink-0 text-fog-2" />
        <span className="truncate">{node.name}</span>
        {hasFindings && <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-critical" />}
      </button>
    );
  }

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ paddingLeft: depth * 14 + 2 }}
        className="flex w-full items-center gap-1 rounded py-1 pr-2 text-left text-[13px] font-medium text-fog-1 hover:bg-panel-raised hover:text-fog-0"
      >
        {open ? <ChevronDown size={13} className="shrink-0" /> : <ChevronRight size={13} className="shrink-0" />}
        {open ? <FolderOpen size={13} className="shrink-0 text-signal-glow" /> : <Folder size={13} className="shrink-0 text-fog-2" />}
        <span className="truncate">{node.name || "/"}</span>
      </button>
      {open && (
        <div>
          {node.children?.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              findingFiles={findingFiles}
              defaultOpen={depth < 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function FileTree({
  root,
  selectedPath,
  onSelect,
  findingFiles,
}: {
  root: FileTreeNode;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  findingFiles: Set<string>;
}) {
  return (
    <div className="space-y-0.5">
      {root.children?.map((child) => (
        <TreeNode
          key={child.path}
          node={child}
          depth={0}
          selectedPath={selectedPath}
          onSelect={onSelect}
          findingFiles={findingFiles}
          defaultOpen={true}
        />
      ))}
    </div>
  );
}
