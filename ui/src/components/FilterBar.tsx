import type { Filters, SortField, SortDir } from '../types'

interface Props {
  filters: Filters
  onFiltersChange: (f: Filters) => void
  sort: { field: SortField; dir: SortDir }
  onSortChange: (s: { field: SortField; dir: SortDir }) => void
  totalResults: number
  filteredResults: number
}

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: 'score', label: 'Score' },
  { value: 'price', label: 'Price' },
  { value: 'title', label: 'Title' },
]

export function FilterBar({ filters, onFiltersChange, sort, onSortChange, totalResults, filteredResults }: Props) {
  const update = (patch: Partial<Filters>) => onFiltersChange({ ...filters, ...patch })

  return (
    <div className="backdrop-blur-xl rounded-2xl p-3 border shadow-2xl bg-card/80 border-border/30 flex flex-wrap items-center gap-3">
      {/* Marketplace filter */}
      <div className="flex gap-1">
        {(['all', 'amazon', 'ebay'] as const).map(m => (
          <button
            key={m}
            onClick={() => update({ marketplace: m })}
            className={`text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors ${
              filters.marketplace === m
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'bg-secondary/50 text-muted-foreground border border-transparent hover:border-border/50'
            }`}
          >
            {m === 'all' ? 'All' : m === 'amazon' ? 'Amazon' : 'eBay'}
          </button>
        ))}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Sort */}
      <div className="flex items-center gap-2">
        <label className="text-xs text-muted-foreground">Sort by</label>
        <select
          value={sort.field}
          onChange={e => onSortChange({ ...sort, field: e.target.value as SortField })}
          className="bg-secondary/50 text-foreground text-xs rounded px-2 py-1 border border-border/30 outline-none"
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <button
          onClick={() => onSortChange({ ...sort, dir: sort.dir === 'asc' ? 'desc' : 'asc' })}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {sort.dir === 'asc' ? '↑' : '↓'}
        </button>
      </div>

      {/* Count */}
      {totalResults > 0 && filteredResults !== totalResults && (
        <span className="text-xs text-muted-foreground font-mono">
          {filteredResults}/{totalResults}
        </span>
      )}
    </div>
  )
}
