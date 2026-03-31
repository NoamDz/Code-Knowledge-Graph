class EventProcessor
  ATTRIBUTES = [:name, :email, :status].freeze

  def dispatch(action, params)
    send("handle_#{action}", params)
  end

  def dynamic_call(method_name, data)
    public_send(method_name, data)
  end

  def literal_send(data)
    send(:process_data, data)
  end

  def handle_create(params)
    params[:name]
  end

  def handle_update(params)
    params[:status]
  end

  def process_data(data)
    data.to_s
  end

  ATTRIBUTES.each do |attr|
    define_method(attr) do
      @attributes[attr]
    end

    define_method("#{attr}=") do |value|
      @attributes[attr] = value
    end
  end
end

class ProxyObject
  def method_missing(method, *args, &block)
    @backend.send(method, *args, &block)
  end

  def respond_to_missing?(method, include_private = false)
    @backend.respond_to?(method, include_private) || super
  end
end

class DataPipeline
  def process(items)
    items.map { |item| item.normalize }
         .select { |item| item.valid? }
         .each { |item| item.save }
  end
end
