import type { SearchResult, SignalDetail } from '../types'

interface Props {
  result: SearchResult
  expanded: boolean
  onToggle: () => void
}

function SignalBar({ label, signal }: { label: string; signal: SignalDetail }) {
  const pct = Math.round(signal.score * 100)
  const color = pct >= 80 ? 'bg-pos' : pct >= 60 ? 'bg-warn' : 'bg-neg'
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-muted-foreground w-28 shrink-0">{label}</span>
        <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
          <div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-[10px] font-mono text-muted-foreground w-8 text-right">{pct}%</span>
      </div>
      {signal.reason && (
        <span className="text-[10px] text-muted-foreground/70 ml-[7.5rem] leading-tight">{signal.reason}</span>
      )}
    </div>
  )
}

export function ResultCard({ result, expanded, onToggle }: Props) {
  const r = result
  const hasScore = r.similarity_score != null
  const scorePct = hasScore ? Math.round(r.similarity_score! * 100) : null
  const scoreColor = scorePct != null
    ? scorePct >= 80 ? 'text-pos' : scorePct >= 60 ? 'text-warn' : 'text-neg'
    : 'text-muted-foreground'

  return (
    <div
      className={`backdrop-blur-xl rounded-2xl border shadow-2xl bg-card/80 border-border/30 transition-all duration-200 ${
        expanded ? 'ring-1 ring-primary/30' : ''
      }`}
    >
      {/* Main row */}
      <button
        onClick={onToggle}
        className="w-full text-left p-3 flex gap-3 items-center cursor-pointer hover:bg-secondary/20 rounded-2xl transition-colors"
      >
        {/* Score on left */}
        <div className="shrink-0 w-12 text-center">
          <span className={`text-lg font-bold font-mono ${scoreColor}`}>
            {scorePct != null ? `${scorePct}` : '--'}
          </span>
          {scorePct != null && <span className={`text-[10px] ${scoreColor}`}>%</span>}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-secondary/80 text-muted-foreground border border-border/30">
              {r.marketplace === 'amazon' ? 'Amazon' : 'eBay'}
            </span>
            {r.badge && (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary border border-primary/20">
                {r.badge}
              </span>
            )}
          </div>
          <h3 className="text-sm text-foreground truncate">{r.title}</h3>
          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
            {r.price != null && (
              <span className="font-mono font-bold text-foreground">${r.price.toFixed(2)}</span>
            )}
            {r.condition && <span>{r.condition}</span>}
            {r.rating != null && <span>★ {r.rating.toFixed(1)}</span>}
            {r.review_count != null && r.review_count > 0 && (
              <span>({r.review_count.toLocaleString()})</span>
            )}
            {r.prime && <span className="font-semibold">Prime</span>}
            {r.shipping && <span>{r.shipping}</span>}
          </div>
        </div>

        {/* Image on right - clickable to listing */}
        <a
          href={r.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          className="w-12 h-12 rounded-lg bg-secondary/50 border border-border/20 overflow-hidden shrink-0 flex items-center justify-center hover:border-primary/40 transition-colors"
          title="View listing"
        >
          {r.image_url ? (
            <img src={r.image_url} alt="" className="w-full h-full object-contain" loading="lazy" />
          ) : (
            <span className="text-[10px] text-muted-foreground">No img</span>
          )}
        </a>

        <span className="text-xs text-muted-foreground shrink-0">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-3 pb-3 border-t border-border/20 pt-3 flex flex-col gap-3">
          {/* Score breakdown with new SignalDetail */}
          {r.score_breakdown && (
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-2">Score Breakdown</h4>
              <div className="flex flex-col gap-2">
                {r.score_breakdown.title_similarity && (
                  <SignalBar label="Title Similarity" signal={r.score_breakdown.title_similarity} />
                )}
                {r.score_breakdown.brand_match && (
                  <SignalBar label="Brand Match" signal={r.score_breakdown.brand_match} />
                )}
                {r.score_breakdown.image_similarity && (
                  <SignalBar label="Image Similarity" signal={r.score_breakdown.image_similarity} />
                )}
                {r.score_breakdown.price_anomaly && (
                  <SignalBar label="Price Anomaly" signal={r.score_breakdown.price_anomaly} />
                )}
                {r.score_breakdown.clip_similarity && (
                  <SignalBar label="CLIP Similarity" signal={r.score_breakdown.clip_similarity} />
                )}
                {r.score_breakdown.llm_assessment && (
                  <SignalBar label="LLM Assessment" signal={r.score_breakdown.llm_assessment} />
                )}
              </div>
              {r.score_breakdown.reasoning && (
                <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
                  {r.score_breakdown.reasoning}
                </p>
              )}
            </div>
          )}

          {/* Extra details */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
            {r.seller && (
              <>
                <span className="text-muted-foreground">Seller</span>
                <span className="font-mono">{r.seller}</span>
              </>
            )}
            {r.location && (
              <>
                <span className="text-muted-foreground">Location</span>
                <span>{r.location}</span>
              </>
            )}
            {r.listing_type && (
              <>
                <span className="text-muted-foreground">Listing Type</span>
                <span>{r.listing_type}</span>
              </>
            )}
            {r.asin && (
              <>
                <span className="text-muted-foreground">ASIN</span>
                <span className="font-mono">{r.asin}</span>
              </>
            )}
          </div>

          <a
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary hover:text-primary/80 transition-colors font-mono truncate"
          >
            {r.url}
          </a>
        </div>
      )}
    </div>
  )
}
