import { useState } from 'react'
import type { SearchResult, Marketplace } from '../types'

interface Props {
  marketplace: Marketplace
  results: SearchResult[]
  status: 'idle' | 'searching' | 'done' | 'error'
}

export function SearchLane({ marketplace, results, status }: Props) {
  const [collapsed, setCollapsed] = useState(true)

  const label = marketplace === 'amazon' ? 'Amazon' : 'eBay'
  const isSearching = status === 'searching'

  return (
    <div className="rounded-2xl border bg-card/80 border-border/30 overflow-hidden transition-all duration-200">
      {/* Header */}
      <button
        onClick={() => setCollapsed(prev => !prev)}
        className="w-full flex items-center gap-3 p-3 cursor-pointer hover:bg-secondary/20 transition-colors"
      >
        <span className="text-sm font-semibold text-foreground">{label}</span>

        <span className="text-xs font-mono text-muted-foreground">
          {isSearching && results.length === 0
            ? 'searching...'
            : `${results.length} result${results.length !== 1 ? 's' : ''}`}
        </span>

        {isSearching && results.length > 0 && (
          <span className="text-[10px] text-muted-foreground animate-pulse">
            fetching more...
          </span>
        )}

        <span className="ml-auto text-xs text-muted-foreground">
          {collapsed ? '▼' : '▲'}
        </span>
      </button>

      {/* Collapsed preview */}
      {collapsed && results.length > 0 && (
        <div className="px-3 pb-2 -mt-1">
          <div className="flex flex-col gap-1">
            {results.slice(0, 3).map((r, i) => (
              <div key={r.url || i} className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="w-1 h-1 rounded-full bg-muted-foreground/50 shrink-0" />
                <span className="truncate flex-1">{r.title}</span>
                {r.price != null && (
                  <span className="font-mono text-foreground shrink-0">${r.price.toFixed(2)}</span>
                )}
              </div>
            ))}
            {results.length > 3 && (
              <span className="text-[10px] text-muted-foreground ml-3">
                +{results.length - 3} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* Expanded */}
      {!collapsed && (
        <div className="px-3 pb-3 flex flex-col gap-1">
          {results.length === 0 && !isSearching && (
            <span className="text-xs text-muted-foreground py-2">No results found.</span>
          )}
          {results.map((r, i) => (
            <div key={r.url || i} className="flex items-center gap-3 py-1.5 border-t border-border/10">
              {r.image_url && (
                <div className="w-10 h-10 rounded bg-secondary/50 overflow-hidden shrink-0">
                  <img src={r.image_url} alt="" className="w-full h-full object-contain" loading="lazy" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-xs text-foreground truncate">{r.title}</p>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  {r.condition && <span>{r.condition}</span>}
                  {r.rating != null && <span>★ {r.rating.toFixed(1)}</span>}
                  {r.shipping && <span>{r.shipping}</span>}
                </div>
              </div>
              {r.price != null && (
                <span className="text-sm font-mono font-bold text-foreground shrink-0">
                  ${r.price.toFixed(2)}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
