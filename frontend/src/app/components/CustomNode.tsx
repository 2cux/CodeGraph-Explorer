import { memo, useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { RFNodeData, NodeKind } from "./graphTransforms";
import { KIND_LABEL, KIND_COLOR, filePathShort } from "./graphTransforms";

const NODE_MIN_WIDTH = 160;

type CustomNodeProps = NodeProps & { data: RFNodeData };

const nodeKindStyles = (kind: NodeKind) => {
  const color = KIND_COLOR[kind];
  return {
    colorBar: {
      width: 4,
      flexShrink: 0 as const,
      background: color,
      borderRadius: "3px 0 0 3px",
    },
    typeLabel: {
      fontSize: 9,
      fontWeight: 600 as const,
      color,
      letterSpacing: "0.5px",
    },
  };
};

const CustomNode = memo(function CustomNode({ data, selected }: CustomNodeProps) {
  const [hovered, setHovered] = useState(false);
  const { symbolId, name, kind, filePath, isCenter, isSelected, hierarchyLevel, hierarchyGroup } = data;
  const fpShort = filePathShort(filePath);
  const styles = nodeKindStyles(kind);
  const isExternal = kind === "external_symbol";

  // Compute border / background based on state
  let borderColor = "var(--cg-border)";
  let bgColor = "var(--cg-bg-panel)";
  let borderWidth = 1;
  let borderStyle = "solid";
  let nodeOpacity = 1;

  if (isExternal) {
    borderStyle = "dashed";
    borderColor = "var(--cg-text-muted)";
    nodeOpacity = 0.55;
  }

  if (isCenter) {
    borderColor = isExternal ? "var(--cg-warning)" : KIND_COLOR[kind];
    borderWidth = 2;
    borderStyle = "solid";
    bgColor = "color-mix(in srgb, var(--cg-accent) 6%, var(--cg-bg-panel))";
  } else if (isSelected || selected) {
    borderColor = "var(--cg-accent)";
    borderWidth = 2;
    borderStyle = "solid";
    bgColor = "color-mix(in srgb, var(--cg-accent) 4%, var(--cg-bg-panel))";
  }

  return (
    <div
      className={`cg-rf-node${isExternal ? " cg-node-external" : ""}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        minWidth: NODE_MIN_WIDTH,
        borderRadius: 6,
        overflow: "hidden",
        border: `${borderWidth}px ${borderStyle} ${borderColor}`,
        background: bgColor,
        opacity: nodeOpacity,
        boxShadow: isCenter
          ? "0 0 0 2px color-mix(in srgb, var(--cg-accent) 20%, transparent)"
          : selected
          ? "0 0 0 2px color-mix(in srgb, var(--cg-accent) 14%, transparent)"
          : "0 1px 3px rgba(0,0,0,0.08)",
        transition: "border-color 120ms ease, box-shadow 120ms ease",
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", height: "100%", minHeight: 44 }}>
        {/* Left color bar */}
        <div style={{
          ...styles.colorBar,
          opacity: isExternal ? 0.5 : 1,
        }} />

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
          {/* Type label with hierarchy depth indicator */}
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={styles.typeLabel}>
              {KIND_LABEL[kind]}
            </span>
            {hierarchyLevel !== undefined && hierarchyLevel > 1 && (
              <span
                style={{
                  width: 4, height: 4, borderRadius: "50%",
                  background: KIND_COLOR[kind],
                  opacity: 0.5,
                  flexShrink: 0,
                }}
                title={`Nested ${hierarchyLevel} levels deep`}
              />
            )}
          </div>

          {/* Name */}
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
            {name}
          </span>

          {/* File path */}
          {fpShort && (
            <span
              className="cg-mono"
              style={{
                fontSize: 10,
                color: "var(--cg-text-muted)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                lineHeight: 1.2,
              }}
            >
              {fpShort}
            </span>
          )}
        </div>
      </div>

      {/* Handles */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 8,
          height: 8,
          background: "var(--cg-accent)",
          border: "2px solid var(--cg-bg-panel)",
          opacity: 0.7,
        }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 8,
          height: 8,
          background: "var(--cg-accent)",
          border: "2px solid var(--cg-bg-panel)",
          opacity: 0.7,
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
          {symbolId}
          {hierarchyGroup && (
            <span style={{ display: "block", color: "var(--cg-text-muted)", fontSize: 9 }}>
              Group: {hierarchyGroup}
            </span>
          )}
        </div>
      )}
    </div>
  );
});

export default CustomNode;
