# frozen_string_literal: true

require "json"
require_relative "../lib/auth_helper"
require_relative "../models/user"

module Services
  class UserService
    include AuthHelper
    extend Logging

    attr_reader :repo, :cache
    attr_accessor :current_user

    def initialize(repo:, cache: nil)
      @repo = repo
      @cache = cache || MemoryCache.new
    end

    def find_user(id)
      cached = cache.get("user:#{id}")
      return cached if cached

      user = repo.find(id)
      cache.set("user:#{id}", user, ttl: 3600) if user
      user
    end

    def create_user(params)
      validate_params!(params)
      user = User.new(params)
      repo.save(user)
      notify_created(user)
      user
    end

    def authenticate(email, password)
      user = repo.find_by_email(email)
      return nil unless user&.valid_password?(password)

      self.current_user = user
      generate_token(user)  # from AuthHelper
    end

    private

    def validate_params!(params)
      raise ArgumentError, "email required" unless params[:email]
      raise ArgumentError, "name required" unless params[:name]
    end

    def notify_created(user)
      EventBus.publish("user.created", user.to_h)
    end
  end
end
