"""Python service with Redis operations."""

import json
import redis

redis_client = redis.Redis(host="localhost", port=6379, db=0)


def get_user_flag(user_id: str) -> str:
    """Read a flag that Lua sets."""
    return redis_client.get(f"user:flags:{user_id}")


def set_job_result(job_id: str, result: dict):
    """Write a result that Lua reads."""
    redis_client.set(f"job:result:{job_id}", json.dumps(result))
    redis_client.publish("job:events", json.dumps({"id": job_id, "done": True}))


def get_config(key: str):
    """Read config from Redis hash."""
    return redis_client.hget("app:config", key)
