import { useId } from 'react'

/**
 * A labelled form control.
 *
 * Every field in the app goes through this. Placeholders alone were not enough:
 * they disappear the moment the professor starts typing, and several fields -
 * both duration inputs especially - had no placeholder at all, so they rendered
 * as a bare number with nothing saying what it meant.
 *
 * The label is always visible and always bound to its control, so a long form
 * stays readable while it is being filled in.
 */
interface FieldProps {
  label: string
  hint?: string
  required?: boolean
  className?: string
  children: (id: string) => React.ReactNode
}

export function Field({ label, hint, required, className = '', children }: FieldProps) {
  const id = useId()
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-xs font-medium text-neutral-700">
        {label}
        {required && <span className="ml-0.5 text-red-600">*</span>}
      </label>
      <div className="mt-1">{children(id)}</div>
      {hint && <p className="mt-0.5 text-[11px] text-neutral-500">{hint}</p>}
    </div>
  )
}

export const inputClass =
  'w-full rounded border border-rule bg-white px-2 py-1 text-xs ' +
  'focus:border-neutral-500 focus:outline-none'

type LabelProps = Omit<FieldProps, 'children'>

/** A labelled text/number input — the common case, without the render prop. */
export function TextField({
  label,
  hint,
  required,
  className,
  ...input
}: LabelProps & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Field label={label} hint={hint} required={required} className={className}>
      {(id) => <input id={id} required={required} className={inputClass} {...input} />}
    </Field>
  )
}

/** A labelled textarea. */
export function TextAreaField({
  label,
  hint,
  required,
  className,
  ...area
}: LabelProps & React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <Field label={label} hint={hint} required={required} className={className}>
      {(id) => (
        <textarea id={id} required={required} className={inputClass} {...area} />
      )}
    </Field>
  )
}
