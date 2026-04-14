import { useState, useCallback, useRef } from 'react'
import { SourceProductCard } from './components/SourceProductCard'
import { SearchLane } from './components/SearchLane'
import { FilterBar } from './components/FilterBar'
import { ResultCard } from './components/ResultCard'
import type { Filters, SortField, SortDir, SearchResult, SourceProduct, JobStats } from './types'

type Phase = 'idle' | 'searching' | 'analyzing' | 'done' | 'error'

let resultIdCounter = 0
function assignId(r: SearchResult): SearchResult {
  if (!r._id) {
    r._id = `result-${++resultIdCounter}`
  }
  return r
}

function NodeConnector() {
  return (
    <div className="flex justify-center py-1">
      <div className="w-px h-6 bg-border/50" />
    </div>
  )
}

function App() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [sourceProduct, setSourceProduct] = useState<SourceProduct | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [maxResults, setMaxResults] = useState(100)

  const [amazonResults, setAmazonResults] = useState<SearchResult[]>([])
  const [ebayResults, setEbayResults] = useState<SearchResult[]>([])

  const [scoredResults, setScoredResults] = useState<SearchResult[]>([])

  const [stats, setStats] = useState<JobStats | null>(null)
  const [currentQuery, setCurrentQuery] = useState<string | null>(null)
  const [queryProgress, setQueryProgress] = useState<{ index: number; total: number } | null>(null)

  const [filters, setFilters] = useState<Filters>({
    marketplace: 'all',
    min_score: 0,
    min_price: null,
    max_price: null,
    condition: null,
  })

  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({
    field: 'score',
    dir: 'desc',
  })

  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showSignalInfo, setShowSignalInfo] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const handleSearch = useCallback(async () => {
    abortRef.current?.abort()
    const abort = new AbortController()
    abortRef.current = abort

    resultIdCounter = 0
    setSourceProduct(null)
    setAmazonResults([])
    setEbayResults([])
    setScoredResults([])
    setStats(null)
    setCurrentQuery(null)
    setQueryProgress(null)
    setError(null)
    setExpandedId(null)
    setPhase('searching')

    try {
      const resp = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_results: maxResults }),
        signal: abort.signal,
      })

      if (!resp.ok || !resp.body) {
        setError(`Server error: ${resp.status}`)
        setPhase('error')
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ') && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6))
              handleSSE(currentEvent, data)
            } catch {
              // skip malformed JSON
            }
            currentEvent = ''
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') return
      setError(String(e))
      setPhase('error')
    }
  }, [maxResults])

  function handleSSE(event: string, data: Record<string, unknown>) {
    switch (event) {
      case 'phase': {
        const p = data.phase as string
        if (p === 'done' || p === 'analyzing' || p === 'searching' || p === 'error') {
          setPhase(p as Phase)
        }
        if (p === 'done' && data.summary) {
          const s = data.summary as Record<string, unknown>
          setStats({
            elapsed_seconds: s.elapsed_seconds as number,
            total_requests: s.total_requests as number,
            soft_limit: s.soft_limit as number,
            remaining: s.remaining as number,
            by_platform: s.by_platform as Record<string, number>,
          })
        }
        break
      }

      case 'source': {
        const s = data as Record<string, unknown>
        setSourceProduct({
          title: (s.title as string) || '',
          brand: (s.brand as string) || '',
          url: (s.url as string) || '',
          price: (s.price as number) ?? null,
          currency: (s.currency as string) || '',
          product_type: (s.product_type as string) || '',
          description: (s.description as string) || '',
          material: (s.material as string) || '',
          color: (s.color as string) || '',
          size: (s.size as string) || '',
          fit: (s.fit as string) || '',
          images: (s.images as string[]) || [],
          search_query: (s.search_query as string) || '',
        })
        break
      }

      case 'query_start': {
        setCurrentQuery(data.query as string)
        setQueryProgress({
          index: data.index as number,
          total: data.total as number,
        })
        break
      }

      case 'result': {
        const r = assignId(data as unknown as SearchResult)
        if (r.marketplace === 'amazon') {
          setAmazonResults(prev => [...prev, r])
        } else {
          setEbayResults(prev => [...prev, r])
        }
        break
      }

      case 'lane_done':
      case 'lane_error':
        break

      case 'stats': {
        setStats({
          elapsed_seconds: data.elapsed_seconds as number,
          total_requests: data.total_requests as number,
          soft_limit: data.soft_limit as number,
          remaining: data.remaining as number,
          by_platform: data.by_platform as Record<string, number>,
        })
        break
      }

      case 'scored_result': {
        const r = assignId(data as unknown as SearchResult)
        setScoredResults(prev => [...prev, r])
        break
      }

      case 'error': {
        setError((data.message as string) || 'Unknown error')
        setPhase('error')
        break
      }
    }
  }

  const allRaw = [...amazonResults, ...ebayResults]
  const displayResults = (phase === 'analyzing' || phase === 'done') ? scoredResults : allRaw

  const filtered = displayResults
    .filter(r => {
      if (filters.marketplace !== 'all' && r.marketplace !== filters.marketplace) return false
      return true
    })
    .sort((a, b) => {
      const dir = sort.dir === 'desc' ? 1 : -1
      switch (sort.field) {
        case 'score': return dir * ((b.similarity_score ?? 0) - (a.similarity_score ?? 0))
        case 'price': return dir * ((a.price ?? 0) - (b.price ?? 0))
        case 'title': return dir * a.title.localeCompare(b.title)
        default: return 0
      }
    })

  const isSearching = phase === 'searching' || phase === 'analyzing'
  const showStep1 = phase === 'searching' || phase === 'analyzing' || phase === 'done'
  const showStep2 = phase === 'analyzing' || phase === 'done'

  const searchingText = currentQuery && queryProgress
    ? `Searching "${currentQuery}" (${queryProgress.index + 1}/${queryProgress.total})`
    : 'Starting scan...'

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-5xl mx-auto flex flex-col">
      {/* Header - centered */}
      <div className="flex flex-col items-center gap-1 mb-8">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/20 border border-primary/30 flex items-center justify-center">
            <span className="text-primary font-bold text-sm">D</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">discomfrt</h1>
        </div>
        <p className="text-xs text-muted-foreground">Comfrt Infringement Detector</p>
      </div>

      {/* Scan Node - centered */}
      <div className="flex flex-col items-center">
        <div className="w-full max-w-lg backdrop-blur-xl rounded-xl p-5 border shadow-2xl bg-card/80 border-border/30 flex flex-col items-center gap-4">
          <p className="text-sm text-muted-foreground text-center">
            Scan Amazon and eBay for potential fake <span className="font-semibold text-foreground">Comfrt</span> listings
          </p>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">Max results</label>
              <select
                value={maxResults}
                onChange={e => setMaxResults(Number(e.target.value))}
                disabled={isSearching}
                className="bg-secondary/50 text-foreground text-xs rounded px-2 py-1.5 border border-border/30 outline-none disabled:opacity-40"
              >
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={200}>200</option>
                <option value={400}>400</option>
              </select>
            </div>

            <button
              onClick={handleSearch}
              disabled={isSearching}
              className="bg-primary text-white text-sm font-semibold rounded-lg px-8 py-3 hover:bg-primary/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >
              {isSearching ? (
                <span className="flex items-center gap-2">
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Scanning...
                </span>
              ) : (
                'Start Scan'
              )}
            </button>
          </div>

          {phase === 'searching' && (
            <p className="text-xs text-muted-foreground animate-pulse">{searchingText}</p>
          )}

          {phase === 'error' && error && (
            <p className="text-xs text-neg">{error}</p>
          )}
        </div>
      </div>

      {/* Reference Node */}
      {sourceProduct && (
        <>
          <NodeConnector />
          <SourceProductCard product={sourceProduct} />
        </>
      )}

      {/* Search Results Node */}
      {showStep1 && (
        <>
          <NodeConnector />
          <div className="backdrop-blur-xl rounded-xl border shadow-2xl bg-card/80 border-border/30 p-4 flex flex-col gap-3">
            <div className="flex flex-col items-center gap-1">
              <div className="flex items-center gap-3">
                <h2 className="text-base font-bold text-foreground">Search Results</h2>
                <span className="text-sm font-mono text-muted-foreground">
                  {allRaw.length} found
                </span>
                {phase === 'searching' && (
                  <span className="w-3 h-3 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Searching for matching products on Amazon and eBay using multiple query variations. Results are deduplicated by product ID.
              </p>
            </div>

            <SearchLane marketplace="amazon" results={amazonResults} status={phase === 'searching' ? 'searching' : 'done'} />
            <SearchLane marketplace="ebay" results={ebayResults} status={phase === 'searching' ? 'searching' : 'done'} />

            {stats && (
              <div className="flex items-center gap-3 text-[10px] text-muted-foreground/60 pt-1 border-t border-border/10">
                <span className="font-mono">{Math.round(stats.elapsed_seconds)}s</span>
                <span className="font-mono">{stats.total_requests} requests</span>
              </div>
            )}
          </div>
        </>
      )}

      {/* Analysis Node */}
      {showStep2 && (
        <>
          <NodeConnector />
          <div className="backdrop-blur-xl rounded-xl border shadow-2xl bg-card/80 border-border/30 p-4 flex flex-col gap-3">
            <div className="flex flex-col items-center gap-1">
              <div className="flex items-center gap-3">
                <h2 className="text-base font-bold text-foreground">Analysis</h2>
                {phase === 'analyzing' && (
                  <>
                    <span className="text-sm text-muted-foreground">
                      {scoredResults.length}/{allRaw.length} scored
                    </span>
                    <span className="w-3 h-3 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                  </>
                )}
                {phase === 'done' && (
                  <span className="text-sm text-muted-foreground">
                    {scoredResults.length} results
                  </span>
                )}
                <button
                  onClick={() => setShowSignalInfo(prev => !prev)}
                  className="w-5 h-5 rounded-full bg-primary/15 border border-primary/30 flex items-center justify-center text-primary text-[10px] font-bold hover:bg-primary/25 transition-colors"
                  title="How scoring works"
                >
                  ?
                </button>
              </div>
              <p className="text-xs text-muted-foreground">
                Each candidate is scored against 8 authentic Comfrt products using 6 independent signals. Higher score = more likely infringement.
              </p>
            </div>

            {/* Signal info panel */}
            {showSignalInfo && (
              <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 flex flex-col gap-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-foreground">How Scoring Works</span>
                  <button onClick={() => setShowSignalInfo(false)} className="text-muted-foreground hover:text-foreground text-xs">close</button>
                </div>
                <div className="flex flex-col gap-2 text-muted-foreground">
                  <div>
                    <span className="font-semibold text-foreground">Title Similarity (30%)</span>
                    <p>Compares the listing title against the brand name using TF-IDF cosine similarity. If a listing says "Comfrt Hoodie" in the title, it scores 85%+ automatically.</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-0.5">Example: "Comfrt Blanket Hoodie Oversized" = 85%, "Oversized Sherpa Hoodie" = 12%</p>
                  </div>
                  <div>
                    <span className="font-semibold text-foreground">Brand Match (20%)</span>
                    <p>Fuzzy matching on brand name. Catches misspellings like "Comfrit" or similar names like "Comfy" (67% match).</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-0.5">Example: "Comfrt" in title = 100%, "Comfy" = 67%, "Nike" = 0%</p>
                  </div>
                  <div>
                    <span className="font-semibold text-foreground">Image Similarity (15%)</span>
                    <p>Perceptual hashing (pHash + dHash) compares the listing image against all 8 reference product photos. Returns the best match.</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-0.5">Example: Same product photo resized = 95%, similar hoodie = 72%, unrelated item = 30%</p>
                  </div>
                  <div>
                    <span className="font-semibold text-foreground">Price Anomaly (15%)</span>
                    <p>Counterfeits are usually much cheaper than retail. A listing at 75% below the authentic price scores very high.</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-0.5">Example: $10 vs $49 retail = 95% (suspicious), $45 = 60% (similar price), $120 = 10% (too expensive)</p>
                  </div>
                  <div>
                    <span className="font-semibold text-foreground">CLIP Embedding (10%)</span>
                    <p>AI vision model (ViT-B-32) compares images semantically. Same product from different angles still scores high, unlike pixel-based hashing.</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-0.5">Example: Same hoodie different angle = 78%, different hoodie brand = 55%, shoes = 20%</p>
                  </div>
                  <div>
                    <span className="font-semibold text-foreground">LLM Assessment (10%)</span>
                    <p>Gemini 2.0 Flash reads both listings and judges infringement probability. Catches copied marketing copy and brand name swaps.</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-0.5">Example: Copied product description = 90%, generic listing = 30%</p>
                  </div>
                </div>
              </div>
            )}

            <FilterBar
              filters={filters}
              onFiltersChange={setFilters}
              sort={sort}
              onSortChange={setSort}
              totalResults={displayResults.length}
              filteredResults={filtered.length}
            />

            <div className="flex flex-col gap-3">
              {filtered.length === 0 && phase === 'done' && (
                <span className="text-xs text-muted-foreground py-4 text-center">
                  No results match the current filters.
                </span>
              )}
              {filtered.map((r, i) => (
                <ResultCard
                  key={r._id || `fallback-${i}`}
                  result={r}
                  expanded={expandedId === (r._id || r.url)}
                  onToggle={() => {
                    const id = r._id || r.url
                    setExpandedId(prev => prev === id ? null : id)
                  }}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default App
