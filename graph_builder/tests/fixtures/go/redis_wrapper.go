package redis

import (
	"context"
	"time"
	"github.com/go-redis/redis/v8"
)

type RedisClient struct {
	client *redis.Client
}

func NewRedisClient(addr string) *RedisClient {
	return &RedisClient{
		client: redis.NewClient(&redis.Options{Addr: addr}),
	}
}

func (r *RedisClient) HGetAsString(ctx context.Context, key, field string) (string, error) {
	return r.client.HGet(ctx, key, field).Result()
}

func (r *RedisClient) GetAsInt(ctx context.Context, key string) (int64, error) {
	return r.client.Get(ctx, key).Int64()
}

func (r *RedisClient) HSetWithExpire(ctx context.Context, key, field string, value interface{}, ttl time.Duration) error {
	pipe := r.client.Pipeline()
	pipe.HSet(ctx, key, field, value)
	pipe.Expire(ctx, key, ttl)
	_, err := pipe.Exec(ctx)
	return err
}

func (r *RedisClient) DeleteKey(ctx context.Context, key string) error {
	return r.client.Del(ctx, key).Err()
}

type Service struct {
	redis *RedisClient
}

func (s *Service) HandleRequest(ctx context.Context, userID string) string {
	val, _ := s.redis.HGetAsString(ctx, "users", userID)
	count, _ := s.redis.GetAsInt(ctx, "counter:"+userID)
	s.redis.HSetWithExpire(ctx, "session:"+userID, "count", count, 24*time.Hour)
	return val
}
