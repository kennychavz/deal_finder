# Architecture: Evolving to Multi-Tenant Infringement Detection

## Where We Are Now

Right now this is a single-tenant app. One FastAPI server, one React frontend, one user clicking "Start Scan." It works well for demonstrating the pipeline, but if we needed to run this for hundreds of clients simultaneously, basically everything about the job lifecycle would need to change. The scoring signals and scraping logic stay the same. It is the orchestration around them that needs to scale.

## Job Orchestration

The first thing I would do is pull the search pipeline out of the HTTP request handler and into a proper job queue. Right now the entire scrape-to-score pipeline lives inside a single SSE stream. That is fine for a demo, but it means if the connection drops, the job is gone.

I would go with **BullMQ** backed by **Redis** for this. BullMQ is a Node.js job queue library that uses Redis as its backing store for persistence and coordination. The reason I would pick it over alternatives like Celery (Python) or SQS (AWS) is that BullMQ gives you built-in support for job priorities, rate limiting, retries with backoff, and parent-child job relationships all out of the box. It also has a clean dashboard (Bull Board) for debugging stuck jobs. Redis gives you the speed and the pub/sub primitives that make real-time job progress updates cheap.

The flow becomes:

```
Client Request -> API Gateway -> Job Queue -> Worker Pool -> Results Store -> Webhook/Poll
```

Each search job fans out into sub-jobs. One per query per marketplace. So a client with 6 queries hitting Amazon and eBay gets 12 sub-jobs. A parent job aggregates and deduplicates the results, then kicks off scoring. Workers are stateless containers that pull from the queue, so scaling is just "add more workers."

The nice thing about this model is that partial results are totally natural. If 3 of your 12 sub-jobs finish, the client can already see those results while the rest are still running.

## Rate Limiting and Client Isolation

This is where it gets interesting. ScraperAPI has rate limits, and we would be sharing those across all clients. The approach I would take:

- **Per-client budgets** tracked in Redis. Each client gets N requests per billing cycle, enforced before any scraper call fires
- **Global concurrency cap** via a semaphore on the ScraperAPI key pool. We cannot let 50 clients all blast requests simultaneously
- **Separate queues per client** so one client's massive job cannot starve everyone else. Round-robin scheduling across queues with burst capacity for paid tiers
- **API key rotation**. Maintain a pool of ScraperAPI keys and assign them per-client so rate limits are independent

The key insight here is that isolation needs to happen at two levels: the queue level (so jobs do not interfere) and the request level (so budget accounting is accurate).

## What We Would Store

| Data | Store | Retention |
|---|---|---|
| Job state (status, progress, errors) | PostgreSQL | 90 days |
| Scored results + signal breakdowns | PostgreSQL (JSONB) | Per client contract |
| Product images (source + candidates) | S3 with CDN | 30 days |
| Reference sets (authentic products) | S3 + PostgreSQL metadata | Permanent |
| CLIP embeddings cache | Redis or pgvector | 7 days |
| Request budget counters | Redis | Rolling window |
| Audit log (who searched what) | PostgreSQL | 1 year |

The CLIP embeddings cache is worth calling out. Embedding the same reference set images on every single job is wasteful. Pre-compute those once when the client uploads their reference set, store them in pgvector or Redis, and just look them up at score time. That alone would cut scoring time roughly in half.

## Retry Strategy and Failure Handling

Scrapers are inherently flaky. Pages change, rate limits hit, CDNs block you. The philosophy here is: **never let one failure kill the whole job.**

- **Scraper failures**: Exponential backoff with 3 attempts at 5s, 15s, 45s delays. If all three fail, mark that query as partial and move on. The client gets results from the queries that did work
- **Signal failures**: Each signal is independent. If image download fails, score using text signals only. If CLIP errors out, the other 5 signals still produce a score. We already do this in the current implementation and it is one of the better design decisions
- **Job-level failures**: Dead-letter queue after 3 full retries. Fire a webhook to the client with the failure reason. They can always re-trigger
- **Idempotency**: Key jobs by (client_id, reference_set_hash, timestamp_bucket) so duplicate submissions just return the existing job instead of burning budget
- **Circuit breaker**: If ScraperAPI is returning over 50% errors over a 5-minute window, pause new scraping jobs and let the queue drain. No point burning requests into a broken upstream

## Observability

You cannot operate something you cannot see. These are the metrics I would track, exported to Prometheus or Datadog:

- **job_duration_seconds**: Histogram by client, marketplace, and phase. This is your primary "is something slow?" signal
- **scraper_requests_total**: Counter by client, marketplace, and status code. Spot rate limiting early
- **signal_score_distribution**: Histogram per signal type. If the distribution shifts suddenly, a signal might be broken
- **signal_failure_rate**: If CLIP starts failing 30% of the time, you want to know before clients notice
- **results_per_job**: If this drops to zero, your scraper is probably blocked
- **dedup_ratio**: What percentage of results are duplicates across queries. Useful for tuning query diversity
- **queue_depth** per client: If it is growing for over 10 minutes, you need more workers or something is stuck

Alerts on: job failure rate over 5%, scraper budget exhaustion projected within 2 hours, signal failure rate over 20%, queue depth growing for over 10 minutes.
