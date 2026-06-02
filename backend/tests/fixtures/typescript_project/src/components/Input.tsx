import React from "react";

export interface InputProps {
  placeholder: string;
}

/**
 * Function component — arrow function assigned to const.
 */
export const Input = (props: InputProps): string => {
  return `<input placeholder="${props.placeholder}" />`;
};

export default Input;
