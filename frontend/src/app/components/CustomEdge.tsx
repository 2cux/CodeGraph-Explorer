import { memo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";
import type { RFEdgeData } from "./graphTransforms";

type CustomEdgeProps = EdgeProps & { data?: RFEdgeData };

const EDGE_LABEL_COLORS: Record<string, string> = {
  calls: "var(--cg-text-secondary)",
  tested_by: "var(--cg-success)",
  imports: "var(--cg-text-muted)",
  references: "var(--cg-text-muted)",
  contains: "var(--cg-text-muted)",
};

function getEdgeStyle(data: RFEdgeData | undefined): {
  stroke: string;
  strokeDasharray: string;
  opacity: number;
  strokeWidth: number;
} {
  const edgeType = data?.edgeType || "calls";
  const confidence = data?.confidence ?? 0.5;
  const isLowConf = confidence < 0.6;

  // Default: solid calls edge
  let stroke = "var(--cg-text-muted)";
  let strokeDasharray = "none";
  let opacity = 0.7;
  let strokeWidth = 1.5;

  if (edgeType === "calls") {
    stroke = "var(--cg-text-secondary)";
    strokeDasharray = "none";
    opacity = 0.75;
    strokeWidth = 1.5;
  } else if (edgeType === "tested_by") {
    stroke = "var(--cg-success)";
    strokeDasharray = "6 3";
    opacity = 0.65;
    strokeWidth = 1.5;
  } else if (edgeType === "imports" || edgeType === "references") {
    stroke = "var(--cg-border-hover)";
    strokeDasharray = "none";
    opacity = 0.35;
    strokeWidth = 1;
  } else if (edgeType === "contains") {
    stroke = "var(--cg-text-muted)";
    strokeDasharray = "2 4";
    opacity = 0.45;
    strokeWidth = 1;
  }

  // Low confidence overrides
  if (isLowConf) {
    stroke = "var(--cg-warning)";
    strokeDasharray = "4 4";
    opacity = 0.5;
    strokeWidth = 1.5;
  }

  return { stroke, strokeDasharray, opacity, strokeWidth };
}

const CustomEdge = memo(function CustomEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
  selected,
}: CustomEdgeProps) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
  });

  const style = getEdgeStyle(data);
  const edgeType = data?.edgeType || "calls";
  const labelColor = EDGE_LABEL_COLORS[edgeType] || "var(--cg-text-muted)";
  const isLowConf = (data?.confidence ?? 0.5) < 0.6;

  // Selected edge gets a glow
  const glowFilter = selected ? "drop-shadow(0 0 3px var(--cg-accent))" : undefined;

  return (
    <>
      {/* Invisible wider hit area */}
      <BaseEdge
        path={edgePath}
        style={{
          stroke: "transparent",
          strokeWidth: 12,
          cursor: "pointer",
        }}
      />
      {/* Visible edge line */}
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: style.stroke,
          strokeWidth: selected ? style.strokeWidth + 1.5 : style.strokeWidth,
          strokeDasharray: style.strokeDasharray,
          opacity: selected ? 1 : style.opacity,
          filter: glowFilter,
          transition: "opacity 150ms ease, stroke-width 150ms ease",
          cursor: "pointer",
        }}
      />
      {/* Edge label */}
      <EdgeLabelRenderer>
        <div
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            fontSize: 9,
            fontFamily: "'JetBrains Mono', monospace",
            color: labelColor,
            background: "var(--cg-bg-canvas)",
            padding: "1px 5px",
            borderRadius: 3,
            border: `1px solid ${isLowConf ? "var(--cg-warning)" : "var(--cg-border)"}`,
            opacity: isLowConf ? 0.7 : 0.85,
            pointerEvents: "all",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
          className="nodrag nopan"
        >
          {edgeType}
          {isLowConf && (
            <span style={{ marginLeft: 3, color: "var(--cg-warning)" }}>
              {" "}{data?.confidence?.toFixed(2)}
            </span>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

export default CustomEdge;
