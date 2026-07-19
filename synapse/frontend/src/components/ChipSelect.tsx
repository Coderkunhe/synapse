import styles from './ChipSelect.module.css'

export interface ChipOption<T extends string | number | null> {
  value: T
  label: string
}

interface ChipSelectProps<T extends string | number | null> {
  options: ChipOption<T>[]
  value: T
  onChange: (value: T) => void
  name?: string
  labelledBy?: string
}

export default function ChipSelect<T extends string | number | null>({
  options,
  value,
  onChange,
  name,
  labelledBy,
}: ChipSelectProps<T>) {
  return (
    <div className={styles.group} role="radiogroup" aria-label={!labelledBy ? name : undefined} aria-labelledby={labelledBy}>
      {options.map(opt => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          className={`${styles.chip} ${value === opt.value ? styles.active : ''}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
