class Preprocessor
  def initialize(config)
    @config = config
    @preprocessors = []
  end

  def scan_for_preprocess(base_path)
    Dir.glob(File.join(base_path, "preprocess", "*.rb")).each do |file|
      require file
    end
  end

  def load_tasks
    entries = Dir.entries(File.join(@config["base_path"], "tasks"))
    entries.each do |entry|
      next unless entry.end_with?(".rb")
      klass = Class.new
      klass.class_eval(IO.read(entry))
    end
  end
end
