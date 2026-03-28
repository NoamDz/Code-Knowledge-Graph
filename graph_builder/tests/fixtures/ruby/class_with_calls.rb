class DataProcessor
  def process(record)
    validated = validate(record)
    transform(validated) if validated
  end

  def validate(record)
    return nil unless record.key?(:id)
    record
  end

  def transform(record)
    record[:name] = record[:name].downcase
    record
  end
end
