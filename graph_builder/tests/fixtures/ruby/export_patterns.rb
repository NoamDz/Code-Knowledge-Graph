# frozen_string_literal: true

# Test fixture for Ruby export pattern detection
# Tests class names, module names, singleton methods, module-level methods

module Exportable
  def self.version
    "1.0.0"
  end

  def self.configure(options = {})
    @config = options
  end

  def instance_method_in_module
    "hello"
  end
end

class BaseProcessor
  attr_reader :name

  def initialize(name)
    @name = name
  end

  def process(data)
    validate(data)
    transform(data)
  end

  def self.create(name)
    new(name)
  end

  def self.default_config
    { timeout: 30, retries: 3 }
  end

  private

  def validate(data)
    raise "Invalid" unless data
  end

  def transform(data)
    data.to_s
  end
end

class SpecialProcessor < BaseProcessor
  def process(data)
    super(data).upcase
  end

  def self.special_factory
    new("special")
  end
end
