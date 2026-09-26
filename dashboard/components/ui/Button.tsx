import type { ButtonHTMLAttributes } from "react";
import styles from "./ui.module.css";

type Variant = "default" | "primary" | "danger" | "ghost";

export function Button({
  variant = "default",
  small = false,
  className,
  type = "button",
  onClick,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean }) {
  const variantClass =
    variant === "primary" ? styles.buttonPrimary : variant === "danger" ? styles.buttonDanger : variant === "ghost" ? styles.buttonGhost : "";
  return (
    <button
      type={type}
      onClick={onClick}
      className={`${styles.button} ${variantClass} ${small ? styles.buttonSmall : ""} ${className ?? ""}`}
      {...rest}
    />
  );
}

export const buttonClass = styles.button;
export const buttonPrimaryClass = styles.buttonPrimary;
