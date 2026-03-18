module Malware
  module Generator
    module Preprocess
      class Active
        def self.process(config)
          validate(config)
          transform(config)
        end

        def self.validate(config)
          raise "Invalid" unless config[:input]
        end

        private

        def self.transform(config)
          config.merge(processed: true)
        end
      end

      class Passive
        def self.analyze(data)
          data.map { |d| d.to_s }
        end
      end
    end
  end
end
