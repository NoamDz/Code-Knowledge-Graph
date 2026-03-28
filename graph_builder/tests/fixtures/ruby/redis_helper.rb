require "redis"

class RedisHelper
  def initialize(config)
    @redis = Redis.new(config)
  end

  def get(key)
    @redis.get(key)
  end

  def set(key, value)
    @redis.set(key, value)
  end

  def get_json(key)
    result = @redis.get(key)
    JSON.parse(result) if result
  end

  def hget(key, sub_key)
    @redis.hget(key, sub_key)
  end

  def eval_script(script, keys, values)
    @redis.eval(script, keys, values)
  end
end
