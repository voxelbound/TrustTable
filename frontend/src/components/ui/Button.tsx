import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    'bg-slate-900 text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200',
  secondary:
    'border border-slate-300 bg-white text-slate-900 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700',
}

/** Shared button primitive (`docs/ui-specification.md` §5). */
export function Button({
  variant = 'primary',
  className,
  type = 'button',
  ...rest
}: ButtonProps) {
  const classes = [
    'rounded px-4 py-2 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
    VARIANT_CLASSES[variant],
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return <button type={type} className={classes} {...rest} />
}
