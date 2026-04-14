export type Marketplace = 'amazon' | 'ebay'

export interface SourceProduct {
  title: string
  brand: string
  url: string
  price: number | null
  currency: string
  product_type: string
  description: string
  material: string
  color: string
  size: string
  fit: string
  images: string[]
  search_query: string  // auto-generated query for marketplace search
}

export interface SearchResult {
  // Internal unique key (assigned client-side to avoid duplicate URL issues)
  _id?: string

  // Common fields
  title: string
  price: number | null
  currency: string
  url: string
  image_url: string
  marketplace: Marketplace

  // Matching/scoring (filled later by matching algo)
  similarity_score: number | null
  score_breakdown: ScoreBreakdown | null

  // Amazon-specific
  asin?: string
  rating?: number | null
  review_count?: number
  prime?: boolean
  badge?: string | null

  // eBay-specific
  condition?: string
  seller?: string
  shipping?: string
  location?: string
  listing_type?: string
}

export interface SignalDetail {
  score: number       // 0-1
  weight: number      // how much this signal counts
  reason: string      // human-readable explanation
  raw: Record<string, unknown>  // debug values
}

export interface ScoreBreakdown {
  overall: number
  reasoning: string   // top reasons joined
  title_similarity?: SignalDetail
  brand_match?: SignalDetail
  image_similarity?: SignalDetail
  price_anomaly?: SignalDetail
  clip_similarity?: SignalDetail
  llm_assessment?: SignalDetail
  [key: string]: unknown  // allow future signals
}

export type SortField = 'score' | 'price' | 'title' | 'marketplace'
export type SortDir = 'asc' | 'desc'

export interface JobStats {
  elapsed_seconds: number
  total_requests: number
  soft_limit: number
  remaining: number
  by_platform: Record<string, number>
}

export interface SearchState {
  source_url: string
  source_product: SourceProduct | null
  status: 'idle' | 'extracting' | 'searching' | 'analyzing' | 'done' | 'error'
  results: SearchResult[]
  error: string | null
  stats: JobStats | null
  current_query: string | null
  query_progress: { index: number; total: number } | null
}

export interface Filters {
  marketplace: 'all' | Marketplace
  min_score: number
  min_price: number | null
  max_price: number | null
  condition: string | null
}
