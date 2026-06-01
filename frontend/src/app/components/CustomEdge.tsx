import { memo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";
import type { RFEdgeData } from "./graphTransforms";
import {
  EDGE_TYPE_STYLE,
  EDGE_TYPE_LABEL_COLOR,
  LOW_CONF_EDGE_STYLE,
  EXTERNAL_EDGE_STYLE,
} from "./nodeStyles";

type CustomEdgeProps = EdgeProps & { data?: RFEdgeData };

function getEdgeStyle(data: RFEdgeData | undefined): {
  stroke: string;
  strokeDasharray: string;
  opacity: number;
  strokeWidth: number;
} {
  const edgeType = data?.edgeType || "calls";
  const confidence = data?.confidence ?? 0.5;
  const isLowConf = confidence < 0.6;
  const isExternal = data?.isExternal === true;

  // External/unresolved: always dimmed
  if (isExternal) return { ...EXTERNAL_EDGE_STYLE };

  const base = EDGE_TYPE_STYLE[edgeType] || EDGE_TYPE_STYLE.calls;

  // Low confidence overrides type defaults
  if (isLowConf) return { ...LOW_CONF_EDGE_STYLE };

  return { ...base };
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
  const labelColor = EDGE_TYPE_LABEL_COLOR[edgeType] || "var(--cg-text-muted)";
  const isLowConf = (data?.confidence ?? 0.5) < 0.6;
  const isExternal = data?.isExternal === true;

  // Selected edge gets glow + full opacity
  const activeStrokeWidth = selected ? style.strokeWidth + 1.5 : style.strokeWidth;
  const activeOpacity = selected ? 1 : style.opacity;
  const glowFilter = selected ? "drop-shadow(0 0 3px var(--cg-accent))" : undefined;

  // Group class for hover + select
  const groupClass = `cg-edge-group${selected ? " cg-edge--highlighted" : ""}`;

  return (
    <g className={groupClass}>
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
          strokeWidth: activeStrokeWidth,
          strokeDasharray: style.strokeDasharray,
          opacity: activeOpacity,
          filter: glowFilter,
          transition: "opacity 150ms ease, stroke-width 150ms ease",
          cursor: "pointer",
        }}
      />
      {/* Edge label — hidden by default, shown on hover/select */}
      <EdgeLabelRenderer>
        <div
          className={`cg-edge-label nodrag nopan${selected ? "" : ""}`}
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
            pointerEvents: "all",
            cursor: "pointer",
            whiteSpace: "nowrap",
            opacity: selected ? 0.85 : undefined,
          }}
        >
          {edgeType}
          {isExternal && (
            <span style={{ marginLeft: 3, color: "var(--cg-text-muted)", fontStyle: "italic" }}>
              {" "}ext
            </span>
          )}
          {isLowConf && (
            <span style={{ marginLeft: 3, color: "var(--cg-warning)" }}>
              {" "}{data?.confidence?.toFixed(2)}
            </span>
          )}
        </div>
      </EdgeLabelRenderer>
    </g>
  );
});

export default CustomEdge;
