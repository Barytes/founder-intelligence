# frozen_string_literal: true

require "json"
require "fileutils"
require "uri"
require "yaml"

module FounderIntelligence
  module Web
    class DataRepository
      EMPTY_SIGNALS = {
        "status" => "empty",
        "message" => "No successful signals have been generated yet."
      }.freeze

      def initialize(root:)
        @root = File.expand_path(root)
      end

      def latest_signals
        path = full_path("data/signals/latest.json")
        return EMPTY_SIGNALS.dup unless File.exist?(path)

        JSON.parse(File.read(path))
      rescue JSON::ParserError
        {
          "status" => "error",
          "message" => "Local signal file is corrupt or unreadable."
        }
      end

      def refresh_status
        path = full_path("data/app/refresh-status.json")
        return { "status" => "idle" } unless File.exist?(path)

        JSON.parse(File.read(path))
      rescue JSON::ParserError
        {
          "status" => "error",
          "message" => "Refresh status file is corrupt or unreadable."
        }
      end

      def latest_run
        run_files = Dir[full_path("data/store/runs/*.jsonl")].sort
        return { "status" => "empty", "message" => "No store runs have been recorded yet." } if run_files.empty?

        last_line = File.readlines(run_files.last).reverse.find { |line| !line.strip.empty? }
        return { "status" => "empty", "message" => "No store runs have been recorded yet." } unless last_line

        JSON.parse(last_line)
      rescue JSON::ParserError
        {
          "status" => "error",
          "message" => "Latest store run is corrupt or unreadable."
        }
      end

      def profile
        path = full_path("config/user-profile.yml")
        {
          "path" => "config/user-profile.yml",
          "content" => File.read(path)
        }
      rescue Errno::ENOENT
        {
          "status" => "error",
          "message" => "config/user-profile.yml is missing."
        }
      end

      def update_profile(content)
        return { "status" => "error", "message" => "Profile content must be a string." } unless content.is_a?(String)

        parsed = parse_yaml_mapping(content)
        validation_error = validate_profile_config(parsed)
        return { "status" => "error", "message" => validation_error } if validation_error

        write_file("config/user-profile.yml", content.end_with?("\n") ? content : "#{content}\n")
        { "status" => "saved", "path" => "config/user-profile.yml" }
      rescue Psych::SyntaxError => error
        {
          "status" => "error",
          "message" => "Invalid YAML: #{error.message}"
        }
      end

      def sources
        content = File.read(full_path("config/sources.yml"))
        config = sources_config
        {
          "path" => "config/sources.yml",
          "content" => content,
          "sources" => source_rows(config)
        }
      rescue Errno::ENOENT
        {
          "status" => "error",
          "message" => "config/sources.yml is missing."
        }
      rescue Psych::SyntaxError => error
        {
          "status" => "error",
          "message" => "Invalid sources YAML: #{error.message}"
        }
      end

      def update_sources(content)
        return { "status" => "error", "message" => "Sources content must be a string." } unless content.is_a?(String)

        config = parse_sources_config(content)
        validation_error = validate_sources_config(config)
        return { "status" => "error", "message" => validation_error } if validation_error

        write_file("config/sources.yml", content.end_with?("\n") ? content : "#{content}\n")
        {
          "status" => "saved",
          "path" => "config/sources.yml",
          "content" => content.end_with?("\n") ? content : "#{content}\n",
          "sources" => source_rows(config)
        }
      rescue Psych::SyntaxError => error
        {
          "status" => "error",
          "message" => "Invalid sources YAML: #{error.message}"
        }
      end

      def update_source_enabled(source_id, enabled)
        return { "status" => "error", "message" => "enabled must be true or false." } unless [true, false].include?(enabled)

        config = sources_config
        source = config.fetch("sources", []).find { |candidate| candidate["id"] == source_id }
        return { "status" => "not_found", "message" => "Source not found." } unless source

        unless source["source_type"] == "rss"
          return { "status" => "error", "message" => "Only RSS sources can be toggled in the current MVP." }
        end

        source["enabled"] = enabled
        write_file("config/sources.yml", YAML.dump(config))
        {
          "status" => "saved",
          "source" => source_row(source)
        }
      end

      private

      def full_path(path)
        File.join(@root, path)
      end

      def write_file(path, content)
        full = full_path(path)
        FileUtils.mkdir_p(File.dirname(full))
        tmp = "#{full}.tmp"
        File.write(tmp, content)
        FileUtils.mv(tmp, full)
      end

      def sources_config
        parse_sources_config(File.read(full_path("config/sources.yml")))
      end

      def parse_sources_config(content)
        parse_yaml_mapping(content)
      end

      def parse_yaml_mapping(content)
        parsed = YAML.safe_load(content, aliases: true)
        parsed.is_a?(Hash) ? parsed : {}
      end

      def validate_profile_config(config)
        return "Profile YAML must be a mapping with a version field." unless config.is_a?(Hash) && config.key?("version")
        return "Profile user must be a mapping." unless config["user"].is_a?(Hash)
        return "Profile user.name is required." if blank?(config.dig("user", "name"))

        goals = config.fetch("goals", [])
        return "Profile goals must be an array." unless goals.is_a?(Array)

        goals.each_with_index do |goal, index|
          return "Profile goal at index #{index} must be a mapping." unless goal.is_a?(Hash)
          return "Profile goal at index #{index} must include title or keywords." if blank?(goal["title"]) && !array_of_strings?(goal["keywords"], allow_empty: false)
        end

        terms = []
        terms.concat(config["interests"]) if config["interests"].is_a?(Array)
        terms.concat(config["watch_entities"]) if config["watch_entities"].is_a?(Array)
        goals.each { |goal| terms.concat(goal["keywords"]) if goal["keywords"].is_a?(Array) }
        return "Profile must include at least one interest, watch_entity, or goal keyword." unless terms.any? { |term| !blank?(term) }

        return "Profile interests must be an array of strings." if config.key?("interests") && !array_of_strings?(config["interests"], allow_empty: false)
        return "Profile watch_entities must be an array of strings." if config.key?("watch_entities") && !array_of_strings?(config["watch_entities"], allow_empty: true)
        return "Profile negative_preferences must be an array of strings." if config.key?("negative_preferences") && !array_of_strings?(config["negative_preferences"], allow_empty: true)
        if config.key?("output_preferences")
          output = config["output_preferences"]
          return "Profile output_preferences must be a mapping." unless output.is_a?(Hash)
          if output.key?("default_top_n") && (!output["default_top_n"].is_a?(Integer) || output["default_top_n"] <= 0)
            return "Profile output_preferences.default_top_n must be a positive integer."
          end
        end

        nil
      end

      def validate_sources_config(config)
        return "Sources YAML must be a mapping with a version field." unless config.is_a?(Hash) && config.key?("version")
        return "Sources YAML must include a sources array." unless config["sources"].is_a?(Array)

        ids = {}
        config["sources"].each_with_index do |source, index|
          return "Source at index #{index} must be a mapping." unless source.is_a?(Hash)

          id = source["id"]
          return "Source at index #{index} must include id." if id.to_s.strip.empty?
          return "Duplicate source id: #{id}." if ids[id]

          ids[id] = true
          source_type = source["source_type"]
          return "Source #{id} must include source_type." if blank?(source_type)
          return "Source #{id} must include name." if blank?(source["name"])
          return "Source #{id} must include provider." if blank?(source["provider"])
          return "Source #{id} must include category." if blank?(source["category"])
          return "Source #{id} enabled must be true or false." unless [true, false].include?(source["enabled"])
          return "Source #{id} tags must be an array of strings." if source.key?("tags") && !array_of_strings?(source["tags"], allow_empty: true)
          schedule_error = validate_schedule(source, "Source #{id}")
          return schedule_error if schedule_error

          if source_type == "rss"
            connection = source["connection"]
            return "Source #{id} connection must be a mapping." unless connection.is_a?(Hash)
            return "Source #{id} connection.rss_url must be http or https." unless valid_http_url?(connection["rss_url"])
          elsif source["enabled"]
            return "Source #{id} uses unsupported source_type #{source_type}; only RSS sources can be enabled in the current MVP."
          end
        end

        templates = config.fetch("source_templates", {})
        return "source_templates must be a mapping." unless templates.is_a?(Hash)

        templates.each do |id, template|
          return "Source template #{id} must be a mapping." unless template.is_a?(Hash)
          return "Source template #{id} must include source_type." if blank?(template["source_type"])
          return "Source template #{id} must not be enabled in the current MVP." if template["enabled"] == true

          schedule_error = validate_schedule(template, "Source template #{id}")
          return schedule_error if schedule_error
        end

        nil
      end

      def validate_schedule(source, label)
        return nil unless source.key?("schedule")
        return "#{label} schedule must be a mapping." unless source["schedule"].is_a?(Hash)

        minutes = source.dig("schedule", "refresh_interval_minutes")
        return nil if minutes.nil?
        return "#{label} schedule.refresh_interval_minutes must be a positive integer." unless minutes.is_a?(Integer) && minutes.positive?

        nil
      end

      def valid_http_url?(value)
        uri = URI.parse(value.to_s)
        %w[http https].include?(uri.scheme) && !blank?(uri.host)
      rescue URI::InvalidURIError
        false
      end

      def array_of_strings?(value, allow_empty:)
        return false unless value.is_a?(Array)
        return false if !allow_empty && value.empty?

        value.all? { |entry| entry.is_a?(String) && !blank?(entry) }
      end

      def blank?(value)
        value.nil? || value.to_s.strip.empty?
      end

      def source_rows(config)
        rows = config.fetch("sources", []).map { |source| source_row(source) }
        template_rows = config.fetch("source_templates", {}).map do |id, source|
          source_row(source.merge("id" => id, "template" => true, "enabled" => false))
        end
        rows + template_rows
      end

      def source_row(source)
        source_type = source["source_type"] || source["type"]
        enabled = source.fetch("enabled", false)
        toggleable = source_type == "rss" && !source["template"]
        {
          "id" => source["id"],
          "name" => source["name"] || source["id"],
          "category" => source["category"] || "uncategorized",
          "type" => source_type || "unknown",
          "provider" => source["provider"],
          "enabled" => enabled,
          "toggleable" => toggleable,
          "runnable" => toggleable && enabled,
          "cadence" => source.dig("schedule", "refresh_interval_minutes") ? "#{source.dig("schedule", "refresh_interval_minutes")} min" : "manual",
          "priority" => source["priority"],
          "tags" => source["tags"] || [],
          "notes" => source["notes"],
          "signal" => source["notes"] || source.dig("connection", "rss_url") || source.dig("connection", "tool") || "Configured source"
        }
      end
    end
  end
end
