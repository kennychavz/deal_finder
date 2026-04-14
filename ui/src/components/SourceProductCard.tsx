import type { SourceProduct } from '../types'

interface Props {
  product: SourceProduct
}

export function SourceProductCard({ product }: Props) {
  const p = product

  return (
    <div className="backdrop-blur-xl rounded-2xl p-3 border shadow-2xl bg-card/80 border-border/30">
      <div className="flex gap-3">
        {/* Image */}
        {p.images.length > 0 && (
          <div className="w-20 h-20 rounded-lg bg-secondary/50 border border-border/20 overflow-hidden shrink-0">
            <img src={p.images[0]} alt="" className="w-full h-full object-contain" loading="lazy" />
          </div>
        )}

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary border border-primary/20">
              Reference Brand
            </span>
            {p.brand && (
              <span className="text-xs text-muted-foreground">{p.brand}</span>
            )}
          </div>
          <h3 className="text-sm font-semibold text-foreground mb-1 truncate">{p.title}</h3>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {p.price != null && (
              <span className="font-mono font-bold text-foreground">
                {p.currency === 'USD' ? '$' : `${p.currency} `}{p.price.toFixed(2)}
              </span>
            )}
            {p.material && <span>{p.material}</span>}
            {p.color && <span>{p.color}</span>}
            {p.size && <span>Size {p.size}</span>}
            {p.fit && <span>{p.fit.split('.')[0]}</span>}
          </div>
        </div>
      </div>

      {/* Search queries */}
      {p.search_query && (
        <div className="mt-2 pt-2 border-t border-border/20 flex items-start gap-2">
          <span className="text-[10px] text-muted-foreground shrink-0 mt-0.5">Queries:</span>
          <div className="flex flex-wrap gap-1">
            {p.search_query.split(' | ').map((q, i) => (
              <span key={i} className="text-[10px] font-mono text-info bg-info/10 px-1.5 py-0.5 rounded">
                {q}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
