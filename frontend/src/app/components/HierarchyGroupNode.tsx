import { memo, useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { RFNodeData, NodeKind } from "./graphTransforms";
import { KIND_LABEL, KIND_COLOR } from "./graphTransforms";

const NODE_MIN_WIDTH = 220;

type HierarchyGroupNodeProps = NodeProps & { data: RFNodeData };

function ChevronRight({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function ChevronDown({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

const HierarchyGroupNode = memo(function HierarchyGroupNode({
  data,
  selected,
}: HierarchyGroupNodeProps) {
  const [hovered, setHovered] = useState(false);
  const {
    symbolId,
    name,
    kind,
    isExpanded = false,
    childCount,
    childKindSummary,
  } = data;

  const styles = nodeKindStyles(kind);

  // Border / background based on state
  let borderColor = "var(--cg-border)";
  let bgColor = "var(--cg-bg-panel)";
  let borderWidth = 1;

  if (selected) {
    borderColor = "var(--cg-accent)";
    borderWidth = 2;
    bgColor = "color-mix(in srgb, var(--cg-accent) 4%, var(--cg-bg-panel))";
  } else if (isExpanded) {
    borderColor = KIND_COLOR[kind];
    bgColor = "color-mix(in srgb, var(--cg-accent) 3%, var(--cg-bg-panel))";
  }

  // Build label: for file groups show filename, for module groups show path
  const displayName = name;

  return (
    <div
      className="cg-rf-node cg-group-parent"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        minWidth: NODE_MIN_WIDTH,
        borderRadius: 8,
        overflow: "visible",
        border: `${borderWidth}px solid ${borderColor}`,
        background: bgColor,
        boxShadow: selected
          ? "0 0 0 2px color-mix(in srgb, var(--cg-accent) 14%, transparent)"
          : "0 1px 3px rgba(0,0,0,0.06)",
        transition: "border-color 120ms ease, box-shadow 120ms ease",
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", height: "100%", minHeight: 52 }}>
        {/* Left color bar */}
        <div
          style={{
            width: 6,
            flexShrink: 0,
            background: KIND_COLOR[kind],
            borderRadius: "4px 0 0 4px",
            opacity: isExpanded ? 1 : 0.65,
          }}
        />

        {/* Content */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            padding: "6px 10px",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            justifyContent: "center",
          }}
        >
          {/* Type label */}
          <span style={styles.typeLabel}>{KIND_LABEL[kind]}</span>

          {/* Group name */}
          <span
            className="cg-mono"
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--cg-text-primary)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              lineHeight: 1.2,
            }}
          >
            {displayName}
          </span>

          {/* Child count badge */}
          {childCount !== undefined && childCount > 0 && (
            <span
              style={{
                fontSize: 10,
                color: "var(--cg-text-muted)",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <span
                style={{
                  display: "inline-block",
                  padding: "1px 6px",
                  borderRadius: 3,
                  background: "var(--cg-bg-subtle)",
                  fontSize: 9,
                  fontWeight: 600,
                  color: "var(--cg-text-secondary)",
                }}
              >
                {childCount} symbols
              </span>
              {childKindSummary && (
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {childKindSummary}
                </span>
              )}
            </span>
          )}
        </div>

        {/* Expand/collapse chevron */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 28,
            flexShrink: 0,
            color: "var(--cg-text-secondary)",
          }}
        >
          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>

      {/* Handles */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 10,
          height: 10,
          background: "var(--cg-accent)",
          border: "2px solid var(--cg-bg-panel)",
          opacity: 0.6,
        }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 10,
          height: 10,
          background: "var(--cg-accent)",
          border: "2px solid var(--cg-bg-panel)",
          opacity: 0.6,
        }}
      />

      {/* Hover tooltip */}
      {hovered && (
        <div
          className="cg-mono"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            marginTop: 4,
            padding: "4px 8px",
            borderRadius: 4,
            background: "var(--cg-bg-tooltip, #1e1e2e)",
            color: "var(--cg-text-primary)",
            fontSize: 10,
            whiteSpace: "nowrap",
            zIndex: 9999,
            pointerEvents: "none",
            border: "1px solid var(--cg-border)",
            maxWidth: 400,
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {symbolId} — Click to {isExpanded ? "collapse" : "expand"}
        </div>
      )}
    </div>
  );
});

function nodeKindStyles(kind: NodeKind) {
  const color = KIND_COLOR[kind];
  return {
    typeLabel: {
      fontSize: 9,
      fontWeight: 600 as const,
      color,
      letterSpacing: "0.5px",
    },
  };
}

export default HierarchyGroupNode;
