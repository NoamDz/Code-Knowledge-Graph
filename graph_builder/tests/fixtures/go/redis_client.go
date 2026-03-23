package server

import (
	"context"
	"fmt"
	"github.com/go-redis/redis/v8"
	"time"
)

type RedisClient struct {
	client *redis.Client
	ctx    context.Context
}

func (r *RedisClient) GetAsString(key string) (string, error) {
	return r.client.Get(r.ctx, key).Result()
}

func (r *RedisClient) Set(key string, value interface{}, ttl time.Duration) error {
	return r.client.Set(r.ctx, key, value, ttl).Err()
}

func (r *RedisClient) HGet(key, field string) (string, error) {
	return r.client.HGet(r.ctx, key, field).Result()
}

type Server struct {
	redisClient *RedisClient
}

func (s *Server) predict(sessionID string) string {
	modelData, _ := s.redisClient.GetAsString("model:latest")
	s.redisClient.Set("prediction:"+sessionID, modelData, 24*time.Hour)
	cached, _ := s.redisClient.HGet("cache:models", "default")
	return cached
}

func (s *Server) customMethods(sessionID string) string {
	val, _ := s.redisClient.HGetAsString("cache:models", "default")
	count, _ := s.redisClient.GetAsInt("counter:" + sessionID)
	s.redisClient.HSetWithExpire("session:"+sessionID, "count", count, 24*time.Hour)
	floatVal, _ := s.redisClient.GetAsFloat("score:" + sessionID)
	return fmt.Sprintf("%s %d %f", val, count, floatVal)
}
