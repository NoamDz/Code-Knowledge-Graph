# BOB Investigation — Round 8: Go Redis Call Site Verification

## Context

Our Go Redis detector finds **40 operations** across all Go files. BOB previously said "93 operations in redis.go". The detector matches callee strings like `r.client.HGet(...)` or `mps.redisClient.GetAsString(...)` against indicator patterns and method name sets.

We need to understand why we only find 40 instead of 93. Either the count of 93 included non-Redis operations, or the Go parser produces callee strings we don't match.

---

## Questions

**Q1.** Show 10 different Redis call lines from the Go codebase (from `redis.go`, `redis_service.go`, or wherever Redis is used). For each line, show:
- The exact line of code
- The file path
- The receiver variable name and its type

Example format:
```
File: src/core/model_prediction/server/common/db/redis.go:45
Line: result, err := r.client.HGet(ctx, key, field).Result()
Receiver: r.client (type: *redis.Client)
```

**Q2.** In the file `redis.go` (or equivalent), how many total function/method calls exist (not just Redis calls)? Is the "93" count specifically Redis operations, or total operations in that file?

**Q3.** Are there Redis calls that use chained method syntax like `.Result()` or `.Err()` at the end? Show 5 examples. Does the Go parser see `r.client.HGet(ctx, key, field).Result()` as one call or two separate calls?

**Q4.** Are there Redis calls through interfaces or function parameters? For example:
```go
func processWithRedis(client redis.Cmdable, key string) {
    client.Get(ctx, key)  // Is "client" the receiver here?
}
```
Show examples if they exist.

**Q5.** Are there Redis pipeline/transaction patterns?
```go
pipe := r.client.Pipeline()
pipe.HGet(ctx, key1, field1)
pipe.HGet(ctx, key2, field2)
pipe.Exec(ctx)
```
If so, how common? The detector might miss `pipe.HGet` because `pipe` isn't in the indicator set.

---

## What Each Answer Enables

| Question | Enables |
|----------|---------|
| Q1 | Verify callee string format matches our detection patterns |
| Q2 | Clarify whether "93" was Redis-specific or total file operations |
| Q3 | Determine if .Result() chaining creates callee strings we don't match |
| Q4 | Determine if interface-based Redis calls need different detection |
| Q5 | Add pipeline/transaction receiver patterns to indicator set |
