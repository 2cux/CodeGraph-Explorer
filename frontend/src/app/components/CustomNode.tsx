import { memo, useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { RFNodeData } from "./graphTransforms";
import { KIND_COLOR, filePathShort } from "./graphTransforms";
import { NODE_DIMS, NODE_TYPE_LABEL } from "./nodeStyles";

type CustomNodeProps = NodeProps & { data: RFNodeData };

/** Build className string for node state CSS classes */
function stateClass(data: RFNodeData, selected: boolean): string {
  const parts: string[] = ["cg-rf-node"];
  const isExternal = data.kind === "external_symbol";
  const isLowConf = data.confidence < 0.6 && !data.isCenter;

  if (data.isCenter) parts.push("cg-node--center");
  else if (data.isSelected || selected) parts.push("cg-node--selected");
  else if (isExternal) parts.push("cg-node--external");
  else if (isLowConf) parts.push("cg-node--low-confidence");

  return parts.join(" ");
}

const CustomNode = memo(function CustomNode({ data, selected }: CustomNodeProps) {
  const [hovered, setHovered] = useState(false);
  const {
    symbolId, name, kind, filePath, isCenter, isSelected,
    hierarchyLevel, hierarchyGroup,
  } = data;
  const fpShort = filePathShort(filePath);
  const isExternal = kind === "external_symbol";
  const isLowConf = data.confidence < 0.6 && !isCenter;
  const color = KIND_COLOR[kind];
  const label = NODE_TYPE_LABEL[kind];

  // Compute border style
  let borderColor = "var(--cg-border)";
  let borderWidth = 1;
  let borderStyle: string = isExternal ? "dashed" : "solid";
  let bgColor = "var(--cg-bg-panel)";

  if (isCenter) {
    borderColor = isExternal ? "var(--cg-warning)" : color;
    borderWidth = 2;
    borderStyle = "solid";
    bgColor = "color-mix(in srgb, var(--cg-accent) 6%, var(--cg-bg-panel))";
  } else if (isSelected || selected) {
    borderColor = "var(--cg-accent)";
    borderWidth = 2;
    borderStyle = "solid";
    bgColor = "color-mix(in srgb, var(--cg-accent) 4%, var(--cg-bg-panel))";
  } else if (isLowConf) {
    borderColor = "color-mix(in srgb, var(--cg-warning) 35%, var(--cg-border))";
  }

  const boxShadow = isCenter
    ? "0 0 0 2px color-mix(in srgb, var(--cg-accent) 20%, transparent)"
    : selected || isSelected
      ? "0 0 0 2px color-mix(in srgb, var(--cg-accent) 14%, transparent)"
      : "0 1px 3px rgba(0,0,0,0.08)";

  return (
    <div
      className={stateClass(data, selected)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        minWidth: NODE_DIMS.minWidth,
        maxWidth: NODE_DIMS.maxWidth,
        borderRadius: 6,
        overflow: "hidden",
        border: `${borderWidth}px ${borderStyle} ${borderColor}`,
        background: bgColor,
        boxShadow,
        transition: "border-color 120ms ease, box-shadow 120ms ease, opacity 200ms ease",
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", height: "100%", minHeight: NODE_DIMS.minHeight }}>
        {/* Left color bar */}
        <div style={{
          width: 4,
          flexShrink: 0,
          background: color,
          opacity: isExternal ? 0.5 : 1,
          borderRadius: "3px 0 0 3px",
        }} />

        {/* Content */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            padding: "6px 10px",
            display: "flex",
            flexDirection: "column",
            gap: 3,
            justifyContent: "center",
          }}
        >
          {/* Row 1: Type badge + name */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                fontSize: 9,
                fontWeight: 600,
                color,
                letterSpacing: "0.5px",
                padding: "1px 4px",
                borderRadius: 2,
                background: `color-mix(in srgb, ${color} 14%, transparent)`,
                flexShrink: 0,
                lineHeight: 1.2,
              }}
            >
              {label}
            </span>
            {hierarchyLevel !== undefined && hierarchyLevel > 1 && (
              <span
                style={{
                  width: 4, height: 4, borderRadius: "50%",
                  background: color,
                  opacity: 0.5,
                  flexShrink: 0,
                }}
                title={`Nested ${hierarchyLevel} levels deep`}
              />
            )}
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
          </div>

          {/* Row 2: File path short */}
          {fpShort && (
            <span
              className="cg-mono cg-node-filepath"
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
          width: 8, height: 8,
          background: "var(--cg-accent)",
          border: "2px solid var(--cg-bg-panel)",
          opacity: 0.7,
        }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 8, height: 8,
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
