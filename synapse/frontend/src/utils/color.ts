/** Deterministic HSL color from a string (e.g., batch_id). */
export function hashBatchColor(id: string): string {
  let hash = 0
  for (let i = 0; i < id.length; i++) {
    hash = id.charCodeAt(i) + ((hash << 5) - hash)
  }
  return `hsl(${Math.abs(hash) % 360}, 50%, 40%)`
}
