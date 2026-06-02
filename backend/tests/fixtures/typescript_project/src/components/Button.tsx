import React from "react";

export interface ButtonProps {
  label: string;
  onClick: () => void;
}

/**
 * A reusable Button component class.
 */
export class Button {
  label: string;

  constructor(props: ButtonProps) {
    this.label = props.label;
  }

  handleClick(): void {
    this.logClick();
    console.log("Button clicked:", this.label);
  }

  logClick(): void {
    // internal helper
  }

  render(): string {
    return `<button>${this.label}</button>`;
  }
}
